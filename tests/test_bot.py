"""Static guards for the robot visit (SPEC 5.3); the behavior itself is checked under gVisor (A1)."""
import pathlib

SANDBOX = pathlib.Path(__file__).resolve().parents[1] / "sandbox"
BOT = (SANDBOX / "bot.mjs").read_text()


def test_robot_has_no_evasion():
    assert "chromium.launch({ headless: true, args: ['--no-sandbox'] })" in BOT
    for trick in ("AutomationControlled", "addInitScript", "userAgent", ".click("):
        assert trick not in BOT


def test_robot_writes_what_verdict_and_investigator_read():
    for key in ("final_url:", "title:", "text:", "status,", "has_password_field:"):
        assert key in BOT
    for artifact in ("robot.json", "final.png", "log('network'", "log('navigations'", "log('blocked'", "log('crash'"):
        assert artifact in BOT


def test_image_ships_the_robot():
    assert "COPY bot.mjs " in (SANDBOX / "Dockerfile").read_text()
