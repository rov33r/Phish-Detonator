import pathlib
import sys

import pytest

# Make `import app...` and `import fixtures...` work without installing the project.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _event_db(tmp_path, monkeypatch):
    """Events emitted during a test go to a throwaway SQLite file, never scans/pd.db."""
    monkeypatch.setenv("PD_DB", str(tmp_path / "pd.db"))
