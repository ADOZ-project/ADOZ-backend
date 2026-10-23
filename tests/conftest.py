import os

os.environ["DATABASE_URL"] = "sqlite:///./test_hipass.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["GEMINI_API_KEY"] = ""
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-1234567890"
os.environ["STORAGE_DIR"] = "./test_storage"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
