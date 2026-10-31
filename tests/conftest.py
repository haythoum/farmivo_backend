import pytest

from app.main import create_app
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
    app = create_app(
        overrides={"repo": repo, "notifier": notifier, "photo_store": MemoryPhotoStore(), "uid": "user-1"}
    )
    app.testing = True
    return app.test_client()


@pytest.fixture
def cow(client):
    r = client.post("/v1/animals", json={"ear_tag": "C1", "name": "Bella", "species": "cattle", "sex": "female",
                                           "date_of_birth": "2022-03-14"})
    assert r.status_code == 201, r.text
    return r.json
