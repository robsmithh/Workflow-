"""Pytest fixtures. Sets up an isolated SQLite DB before the app is imported."""
import os
import tempfile

# Configure environment BEFORE importing the app (engine is built at import time).
_TMP = tempfile.mkdtemp(prefix="wf-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'test.db')}"
os.environ["WORK_DIR"] = os.path.join(_TMP, "runs")
os.environ["API_KEY"] = ""  # disable auth for tests
os.environ["PYTHON_EXECUTABLE"] = "python"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
