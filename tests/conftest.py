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
def make_client(repo, notifier):
    """A test client signed in as ``uid``; all clients share one database, so several people can interact."""
    photos = MemoryPhotoStore()

    def make(uid: str, email: str | None = None, name: str | None = None):
        app = create_app(overrides={"repo": repo, "notifier": notifier, "photo_store": photos,
                                    "uid": uid, "email": email or f"{uid}@example.com", "name": name})
        app.testing = True
        return app.test_client()

    return make


@pytest.fixture
def client(make_client):
    """The farm owner: user-1 with a farm created through POST /v1/farms."""
    c = make_client("user-1", name="Owner One")
    r = c.post("/v1/farms", json={"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"})
    assert r.status_code == 201, r.text
    return c


@pytest.fixture
def cow(client):
    r = client.post("/v1/animals", json={"ear_tag": "C1", "name": "Bella", "species": "cattle", "sex": "female",
                                           "date_of_birth": "2022-03-14"})
    assert r.status_code == 201, r.text
    return r.json
