"""Sandbox lifecycle (SPEC 5.2): one throwaway container per visit, driven through the docker CLI.

Every docker command is a fixed argument list (CLAUDE.md rule 4) and no host secret is passed in.
"""
import os
import pathlib
import re
import subprocess
import time

IMAGE = "pd-sandbox:latest"
NETWORK = "pd-net"  # created and locked down by deploy/netlock.sh; never created here, so a missing lock fails loudly
RESOLV_CONF = "/etc/phishdet/resolv.conf"  # Docker's embedded DNS does not answer under gVisor
PROFILES = ("robot", "victim", "victim_mobile")
LIMITS = {"memory": "2g", "cpus": 2, "pids": 512, "seconds": 120}
READY_SECONDS = 20
BACKSTOP_GRACE = 30

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_running: dict[str, pathlib.Path] = {}  # container name -> host out dir


def _runtime() -> str:
    return os.environ.get("PD_RUNTIME", "runsc")


def _docker(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, errors="replace",
                          timeout=timeout, check=False)


def _emit(scan_id: str, type: str, payload: dict) -> None:
    try:
        from app import db
    except ImportError:  # app/db.py is not merged yet
        return
    db.emit(scan_id, type, payload)


def out_dir(scan_id: str, visit: str) -> pathlib.Path:
    """Host path mounted at /out."""
    for label in (scan_id, visit):
        if not _NAME.fullmatch(label):
            raise ValueError(f"invalid scan id or visit label: {label!r}")
    return pathlib.Path(os.environ.get("PD_SCANS_DIR", "scans")) / scan_id / visit


def _run_args(name: str, scan_id: str, profile: str, out: pathlib.Path) -> list[str]:
    runtime = _runtime()
    args = ["run", "-d", "--name", name, "--label", f"pd.scan={scan_id}", f"--runtime={runtime}",
            "--network", NETWORK, "--dns", "1.1.1.1",
            "--read-only", "--tmpfs", "/tmp:size=512m",
            # runc mounts a tmpfs here as root-only, and Chrome then exits; gVisor hides this.
            "--tmpfs", "/home/pd:size=256m,uid=10001,gid=10001,mode=0700",
            "--shm-size=1g", f"--memory={LIMITS['memory']}", f"--memory-swap={LIMITS['memory']}",
            f"--cpus={LIMITS['cpus']}", f"--pids-limit={LIMITS['pids']}",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10001:10001",
            "-e", f"PD_PROFILE={profile}",
            "-v", f"{out.resolve()}:/out"]
    if runtime == "runsc":  # only gVisor needs the file, and a laptop does not have it
        args += ["-v", f"{RESOLV_CONF}:/etc/resolv.conf:ro"]
    # The caller enforces the wall limit. The finite sleep only ends sandboxes left behind by a dead app.
    return args + [IMAGE, "sleep", str(LIMITS["seconds"] + BACKSTOP_GRACE)]


def _start_browser(container: str) -> None:
    started = _docker(["exec", "-d", container, "/opt/pd/victim-start.sh"])
    if started.returncode != 0:
        raise RuntimeError(f"victim browser did not start: {started.stderr.strip()[:300]}")
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        if exec_in(container, ["test", "-f", "/tmp/recorder.ready"], timeout=10)[0] == 0:
            return
        time.sleep(0.5)
    log = exec_in(container, ["tail", "-n", "20", "/tmp/recorder.log"], timeout=10)[1]
    raise RuntimeError(f"recorder not ready after {READY_SECONDS} s: {log.strip()[-500:]}")


def start_visit(scan_id: str, visit: str, profile: str) -> str:
    """Start a fresh sandbox and return its container name. Victim profiles come with Chrome running."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile!r}")
    out = out_dir(scan_id, visit)
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o777)  # uid 10001 in the container and the host process both write here
    name = f"pd-{scan_id}-{visit}"  # app/agent.py reads the visit label back from this
    try:
        run = _docker(_run_args(name, scan_id, profile, out), timeout=60)
    except subprocess.TimeoutExpired:
        stop_visit(name)
        raise
    if run.returncode != 0:
        # A name clash must not remove the container that already holds the name.
        if "is already in use" not in run.stderr:
            stop_visit(name)
        raise RuntimeError(f"docker run failed: {run.stderr.strip()[:300]}")
    _running[name] = out
    try:
        if profile != "robot":
            _start_browser(name)
        _emit(scan_id, "sandbox_created", {"visit": visit, "profile": profile, "container": name,
                                           "runtime": _runtime(), "limits": dict(LIMITS)})
    except BaseException:
        stop_visit(name)
        raise
    return name


def exec_in(container: str, args: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command in the sandbox. Output is stdout, plus stderr when the command fails."""
    try:
        done = _docker(["exec", container, *args], timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    if done.returncode != 0:
        return done.returncode, done.stdout + done.stderr
    return 0, done.stdout


def _drop_special_files(root: pathlib.Path) -> None:
    """The sandbox is untrusted: a symlink left in /out could make the host read or upload its own files."""
    for folder, dirs, files in os.walk(root):  # does not follow symlinked folders
        for entry in dirs + files:
            path = pathlib.Path(folder) / entry
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                path.unlink(missing_ok=True)


def stop_visit(container: str) -> None:
    """Destroy the sandbox. Never raises: it runs in finally blocks."""
    try:
        _docker(["rm", "-f", container])
    except (OSError, subprocess.SubprocessError):
        pass
    out = _running.pop(container, None)
    if out is not None:
        try:
            _drop_special_files(out)
        except OSError:
            pass
