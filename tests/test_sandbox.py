"""app/sandbox.py with docker stubbed out: argument lists, cleanup, and error handling."""
import stat
import subprocess

import pytest

from app import sandbox


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.results = {}  # docker subcommand or in-container program -> (code, stdout, stderr) or an exception

    def __call__(self, argv, **kwargs):
        assert argv[0] == "docker" and not kwargs.get("shell")
        self.calls.append(argv[1:])
        key = argv[1]
        if key == "exec" and argv[2] != "-d":
            key = argv[3]
        result = self.results.get(key, (0, "", ""))
        if isinstance(result, BaseException):
            raise result
        return subprocess.CompletedProcess(argv, *result)

    def of(self, command):
        return [c for c in self.calls if c[0] == command]


@pytest.fixture
def docker(monkeypatch, tmp_path):
    fake = FakeDocker()
    monkeypatch.setattr(sandbox.subprocess, "run", fake)
    monkeypatch.setattr(sandbox.time, "sleep", lambda s: None)
    monkeypatch.setattr(sandbox, "_running", {})
    monkeypatch.setenv("PD_SCANS_DIR", str(tmp_path))
    monkeypatch.setenv("PD_RUNTIME", "runsc")
    return fake


def pairs(argv):
    return list(zip(argv, argv[1:], strict=False))


def test_run_flags_under_runsc(docker, tmp_path):
    name = sandbox.start_visit("s1", "robot", "robot")
    assert name == "pd-s1-robot"
    run = docker.of("run")[0]
    for flag in ("--runtime=runsc", "--read-only", "--memory=2g", "--memory-swap=2g", "--cpus=2", "--pids-limit=512"):
        assert flag in run
    for pair in (("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"), ("--user", "10001:10001"),
                 ("--network", "pd-net"), ("-e", "PD_PROFILE=robot"),
                 ("--tmpfs", "/home/pd:size=256m,uid=10001,gid=10001,mode=0700"),
                 ("-v", f"{tmp_path}/s1/robot:/out"), ("-v", "/etc/phishdet/resolv.conf:/etc/resolv.conf:ro")):
        assert pair in pairs(run)
    assert run[-3:] == ["pd-sandbox:latest", "sleep", "150"]
    assert not docker.of("exec")  # the robot visit needs no browser start


def test_runc_keeps_the_locked_network_and_skips_the_resolv_mount(docker, monkeypatch):
    monkeypatch.setenv("PD_RUNTIME", "runc")
    sandbox.start_visit("s1", "robot", "robot")
    run = docker.of("run")[0]
    assert "--runtime=runc" in run and ("--network", "pd-net") in pairs(run)
    assert not any("resolv.conf" in a for a in run)


def test_relative_scans_dir_is_mounted_absolute(docker, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PD_SCANS_DIR", "scans")
    sandbox.start_visit("s1", "robot", "robot")
    assert ("-v", f"{tmp_path.resolve()}/scans/s1/robot:/out") in pairs(docker.of("run")[0])


def test_out_dir_is_writable_by_the_sandbox_user(docker, tmp_path):
    sandbox.start_visit("s1", "robot", "robot")
    assert stat.S_IMODE((tmp_path / "s1" / "robot").stat().st_mode) == 0o777


@pytest.mark.parametrize("profile", ["victim", "victim_mobile"])
def test_victim_starts_browser_and_waits_for_recorder(docker, profile):
    name = sandbox.start_visit("s1", f"{profile}-3", profile)
    assert docker.of("exec") == [["exec", "-d", name, "/opt/pd/victim-start.sh"],
                                 ["exec", name, "test", "-f", "/tmp/recorder.ready"]]


def test_recorder_never_ready_removes_the_container(docker, monkeypatch):
    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(clock))
    docker.results = {"test": (1, "", ""), "tail": (0, "boom", "")}
    with pytest.raises(RuntimeError, match="boom"):
        sandbox.start_visit("s1", "victim", "victim")
    assert docker.of("rm") == [["rm", "-f", "pd-s1-victim"]]


@pytest.mark.parametrize("result", [(125, "", "no such network"), subprocess.TimeoutExpired("docker", 60)])
def test_failed_run_removes_the_container(docker, result):
    docker.results = {"run": result}
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        sandbox.start_visit("s1", "robot", "robot")
    assert docker.of("rm")


def test_name_clash_leaves_the_other_container_alone(docker):
    docker.results = {"run": (125, "", 'The container name "/pd-s1-robot" is already in use')}
    with pytest.raises(RuntimeError):
        sandbox.start_visit("s1", "robot", "robot")
    assert not docker.of("rm")


@pytest.mark.parametrize("scan_id, visit", [("..", "robot"), ("s1", "../x"), ("s1", "a/b"), ("s1", "-rm"), ("", "robot")])
def test_bad_labels_are_rejected(docker, scan_id, visit):
    with pytest.raises(ValueError):
        sandbox.start_visit(scan_id, visit, "robot")
    assert not docker.calls


def test_unknown_profile_is_rejected(docker):
    with pytest.raises(ValueError):
        sandbox.start_visit("s1", "robot", "root")
    assert not docker.calls


def test_exec_in_returns_clean_stdout_on_success(docker):
    docker.results = {"agent-browser": (0, "ok\n", "warning\n")}
    assert sandbox.exec_in("c", ["agent-browser", "get", "url"]) == (0, "ok\n")
    assert docker.calls == [["exec", "c", "agent-browser", "get", "url"]]


def test_exec_in_includes_stderr_on_failure(docker):
    docker.results = {"agent-browser": (1, "", "Unknown ref")}
    assert sandbox.exec_in("c", ["agent-browser"]) == (1, "Unknown ref")


def test_exec_in_timeout_does_not_raise(docker):
    docker.results = {"sleep": subprocess.TimeoutExpired("docker", 1)}
    assert sandbox.exec_in("c", ["sleep", "9"], timeout=1)[0] == 124


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("docker", 30), FileNotFoundError("docker")])
def test_stop_visit_never_raises(docker, error):
    docker.results = {"rm": error}
    sandbox.stop_visit("pd-s1-robot")


def test_stop_visit_drops_links_left_by_the_sandbox(docker, tmp_path):
    name = sandbox.start_visit("s1", "robot", "robot")
    out = tmp_path / "s1" / "robot"
    secret = tmp_path / "host-secret"
    secret.write_text("key")
    (out / "robot.json").symlink_to(secret)
    (out / "frames").mkdir()
    (out / "frames" / "1.jpg").write_text("jpg")
    sandbox.stop_visit(name)
    assert not (out / "robot.json").is_symlink()
    assert (out / "frames" / "1.jpg").exists() and secret.read_text() == "key"
