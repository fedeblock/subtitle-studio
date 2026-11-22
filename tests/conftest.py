import os
import tempfile

# Every test DB and upload lives outside real user data.
_TEST_ROOT = tempfile.TemporaryDirectory(prefix="studio-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT.name}/test.db"
os.environ["DATA_DIR"] = f"{_TEST_ROOT.name}/data"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["STUDIO_DATA"] = os.environ["DATA_DIR"]
os.environ["STUDIO_TOKEN"] = "test-only-token"

import pytest  # noqa: E402 — configure isolated storage before importing the app
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.core import Base, engine  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client
