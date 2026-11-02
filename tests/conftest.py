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


class FakeMailer:
    """Records the verification emails instead of sending them."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []  # (to, code)
        self.langs: list[str] = []  # language of each email
        self.fail = False

    def send_code(self, to, code, minutes, lang="en"):
        from app.services.mailer import MailError

        if self.fail:
            raise MailError("smtp down")
        self.sent.append((to, code))
        self.langs.append(lang)

    @property
    def last_code(self):
        return self.sent[-1][1]


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def make_client(repo, notifier, mailer):
    """A test client signed in as ``uid``; all clients share one database, so several people can interact.

    ``verified`` is the Firebase token's email_verified claim: True by default so feature tests skip the
    email code; the verification tests pass False.
    """
    photos = MemoryPhotoStore()

    def make(uid: str, email: str | None = None, name: str | None = None, verified: bool = True):
        app = create_app(overrides={"repo": repo, "notifier": notifier, "photo_store": photos, "mailer": mailer,
                                    "uid": uid, "email": email or f"{uid}@example.com", "name": name,
                                    "email_verified": verified})
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
