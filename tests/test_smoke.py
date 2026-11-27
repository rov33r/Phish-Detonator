"""Smoke tests: every module imports and the app answers /api/health.

Catches the breakage that hurts most on a shared trunk: syntax errors, bad imports,
and a renamed interface. Lane-specific tests go in tests/test_<module>.py.
"""
import importlib
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = sorted(
    ".".join(p.relative_to(ROOT).with_suffix("").parts)
    for pkg in ("app", "fixtures")
    for p in (ROOT / pkg).glob("*.py")
    if p.name != "__init__.py"
)

# Interfaces from CLAUDE.md section 7. Renaming one breaks another lane.
INTERFACES = {
    "app.db": ["emit", "update_scan"],
    "app.sandbox": ["start_visit", "exec_in", "stop_visit", "out_dir"],
    "app.agent": ["run_victim"],
    "app.investigator": ["plan", "next_step"],
    "app.verdict": ["decide"],
    "app.orchestrator": ["run_scan", "dispatch"],
    "app.stats": ["watch", "totals"],
    "app.report": ["write_manifest", "verify"],
}


@pytest.mark.parametrize("name", MODULES or ["<none yet>"])
def test_module_imports(name):
    if name == "<none yet>":
        pytest.skip("no modules yet")
    importlib.import_module(name)


@pytest.mark.parametrize("module,functions", INTERFACES.items())
def test_interfaces_exist(module, functions):
    if not (ROOT / (module.replace(".", "/") + ".py")).exists():
        pytest.skip(f"{module} not written yet")
    mod = importlib.import_module(module)
    missing = [f for f in functions if not callable(getattr(mod, f, None))]
    assert not missing, f"{module} is missing interface functions: {missing}"


def test_health_endpoint():
    if not (ROOT / "app" / "main.py").exists():
        pytest.skip("app/main.py not written yet")
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_brands_json_valid():
    path = ROOT / "app" / "brands.json"
    if not path.exists():
        pytest.skip("brands.json not written yet")
    brands = json.loads(path.read_text())
    assert isinstance(brands, dict) and "Vexalo" in brands
