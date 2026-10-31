import pytest
from fastapi.testclient import TestClient

from app.deps import get_current_uid, get_notifier, get_photo_store, get_repo
from app.main import app
from app.repository import InMemoryRepository
from app.services.notifier import NullNotifier
from app.services.photos import MemoryPhotoStore


@pytest.fixture
def repo():
    return InMemoryRepository()


@pytest.fixture
def notifier():
    return NullNotifier()


@pytest.fixture
def client(repo, notifier):
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_notifier] = lambda: notifier
    app.dependency_overrides[get_photo_store] = lambda: MemoryPhotoStore()
    app.dependency_overrides[get_current_uid] = lambda: "user-1"
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def cow(client):
    r = client.post("/v1/animals", json={"ear_tag": "C1", "name": "Bella", "species": "cattle", "sex": "female",
                                           "date_of_birth": "2022-03-14"})
    assert r.status_code == 201, r.text
    return r.json()
