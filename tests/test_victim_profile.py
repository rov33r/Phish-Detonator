"""Static guards for issue #22: the device profile must not depend on per-page CDP overrides alone."""
import pathlib

SANDBOX = pathlib.Path(__file__).resolve().parents[1] / "sandbox"
START = (SANDBOX / "victim-start.sh").read_text()
RECORDER = (SANDBOX / "recorder.mjs").read_text()


def test_mobile_chrome_starts_with_phone_flags():
    branch = START.split("= victim_mobile ]; then")[1].split("\nelse\n")[0]
    for flag in ("--window-size=412,915", "--touch-events=enabled", "--user-agent=", "Android", "Mobile Safari"):
        assert flag in branch


def test_every_tab_gets_the_stockholm_timezone_from_the_start():
    assert "TZ=Europe/Stockholm LANGUAGE=sv-SE pd-chrome" in START


def test_device_values_are_set_by_an_init_script_before_pages_are_watched():
    assert "fix('hardwareConcurrency', 8)" in RECORDER and "fix('maxTouchPoints', 5)" in RECORDER
    install = RECORDER.index("addInitScript(deviceScript, PROFILE === 'victim_mobile')")
    assert install < RECORDER.index("context.on('page', watch)") < RECORDER.index("recorder.ready', PROFILE")
