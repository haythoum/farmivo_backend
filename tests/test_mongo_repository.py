import pytest

mongomock = pytest.importorskip("mongomock")

from app.repository import MongoRepository  # noqa: E402


@pytest.fixture
def repo():
    return MongoRepository(mongomock.MongoClient()["test"])


def test_crud_and_filters(repo):
    path = "farms/f1/animals"
    a = repo.create(path, {"ear_tag": "A", "status": "active"})
    repo.create(path, {"ear_tag": "B", "status": "sold"})
    repo.create("farms/f2/animals", {"ear_tag": "Z", "status": "active"})  # other path is isolated
    assert a["id"] and "_id" not in a and "farm_id" not in a
    assert [r["ear_tag"] for r in repo.list(path, order_by="ear_tag")] == ["A", "B"]
    assert [r["ear_tag"] for r in repo.list(path, [("status", "==", "sold")])] == ["B"]
    assert len(repo.list(path, [("status", "in", ["active", "sold"])])) == 2
    assert repo.update(path, a["id"], {"name": "Bella"})["name"] == "Bella"
    assert repo.update(path, "missing", {"x": 1}) is None
    assert repo.delete(path, a["id"]) is True and repo.delete(path, a["id"]) is False


def test_set_keeps_created_at(repo):
    first = repo.set("farms", "f1", {"name": "One"})
    second = repo.set("farms", "f1", {"name": "Two"})
    assert second["created_at"] == first["created_at"] and second["name"] == "Two"
    assert [f["name"] for f in repo.list("farms")] == ["Two"]


def test_one_collection_per_type(repo):
    a = repo.create("farms/f1/animals", {"ear_tag": "A"})
    raw = repo._db["animals"].find_one({"_id": a["id"]})
    assert raw["farm_id"] == "f1" and raw["ear_tag"] == "A"
    repo.set("users/u1/devices", "tok", {"platform": "ios"})
    assert repo._db["devices"].find_one({"_id": "tok"})["user_id"] == "u1"
