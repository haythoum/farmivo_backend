"""Regression tests for the backend review of 2026-11-03 (see docs/REVIEW_2026-11-03.md)."""
import io
from datetime import date, datetime, timedelta

import pytest

from app.repository import InMemoryRepository


def iso(days=0):
    from app.utils import today

    return (today() + timedelta(days=days)).isoformat()


# ------------------------------------------------------------ compare-and-set
def test_update_where_only_succeeds_once():
    repo = InMemoryRepository()
    repo.create("farms/f/members", {"status": "pending"}, doc_id="u")
    assert repo.update_where("farms/f/members", "u", {"status": "pending"}, {"status": "active"})["status"] == "active"
    assert repo.update_where("farms/f/members", "u", {"status": "pending"}, {"status": "rejected"}) is None
    assert repo.get("farms/f/members", "u")["status"] == "active"
    assert repo.update_where("farms/f/members", "missing", {}, {"x": 1}) is None


def test_second_birth_on_same_breeding_is_refused(client, cow):
    bull = client.post("/v1/animals", json={"ear_tag": "B1", "species": "cattle", "sex": "male"}).json
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "sire_id": bull["id"], "mating_date": iso(-10)}).json
    one = client.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": iso(), "offspring": [{"ear_tag": "K1", "sex": "male"}]})
    assert one.status_code == 201
    two = client.post(f"/v1/breedings/{b['id']}/births", json={"birth_date": iso(), "offspring": [{"ear_tag": "K2", "sex": "male"}]})
    assert two.status_code == 409
    assert [a["ear_tag"] for a in client.get("/v1/animals?q=K").json] == ["K1"]


def test_delivered_only_through_birth(client, cow):
    b = client.post("/v1/breedings", json={"dam_id": cow["id"], "mating_date": iso(-10)}).json
    r = client.patch(f"/v1/breedings/{b['id']}", json={"pregnancy_status": "delivered"})
    assert r.status_code == 422
    assert client.patch(f"/v1/breedings/{b['id']}", json={"pregnancy_status": "confirmed"}).status_code == 200


# ------------------------------------------------------------------ time zone
def test_today_uses_the_farm_time_zone():
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.utils import today

    settings = get_settings()
    old = settings.timezone
    try:
        for tz in ("Pacific/Kiritimati", "Etc/GMT+12", "Africa/Tunis"):
            settings.timezone = tz
            assert today() == datetime.now(ZoneInfo(tz)).date()
        settings.timezone = "Not/AZone"
        assert today() == date.today()  # bad setting: server date, never a crash
    finally:
        settings.timezone = old


# ------------------------------------------------------------------- animals
def test_patch_cannot_set_future_birth_date(client, cow):
    future = (date.today() + timedelta(days=30)).isoformat()
    r = client.patch(f"/v1/animals/{cow['id']}", json={"date_of_birth": future})
    assert r.status_code == 422
    assert client.get(f"/v1/animals/{cow['id']}").json["date_of_birth"] == "2022-03-14"


def test_create_ignores_outside_photo_url(client):
    r = client.post("/v1/animals", json={"ear_tag": "P1", "species": "goat", "sex": "female",
                                         "photo_url": "https://tracker.example/pixel.png"})
    assert r.status_code == 201 and r.json["photo_url"] is None


def _upload(client, animal_id):
    return client.post(f"/v1/animals/{animal_id}/photo",
                       data={"file": (io.BytesIO(b"\xff\xd8data"), "a.jpg", "image/jpeg")},
                       content_type="multipart/form-data")


def test_replaced_and_deleted_photos_are_removed(client, cow, photo_store):
    first = _upload(client, cow["id"]).json["photo_url"]
    second = _upload(client, cow["id"]).json["photo_url"]
    keys = list(photo_store.files)
    assert len(keys) == 1 and second.endswith(keys[0]) and first != second
    assert client.delete(f"/v1/animals/{cow['id']}").status_code == 204
    assert photo_store.files == {}


def test_photo_route_headers(make_client):
    from app.main import create_app

    class Store:
        def read(self, file_id):
            return (b"<html>", "text/html") if file_id == "evil" else (b"\xff\xd8", "image/jpeg")

    app = create_app(overrides={"repo": InMemoryRepository(), "photo_store": Store(), "uid": "x"})
    c = app.test_client()
    ok = c.get("/v1/photos/abc")
    assert ok.headers["Content-Type"] == "image/jpeg" and ok.headers["X-Content-Type-Options"] == "nosniff"
    evil = c.get("/v1/photos/evil")
    assert evil.headers["Content-Type"] == "application/octet-stream"


def test_photo_id_helper():
    from app.services.photos import photo_id

    assert photo_id("http://h:8000/v1/photos/0123456789abcdef0123456789abcdef") == "0123456789abcdef0123456789abcdef"
    assert photo_id("https://storage.test/x.jpg") is None and photo_id(None) is None


# ------------------------------------------------------------------- numbers
@pytest.mark.parametrize("amount", [0, -5, 1e13, float("inf")])
def test_absurd_amounts_rejected(client, amount):
    r = client.post("/v1/transactions", data=f'{{"type":"expense","category":"feed","amount":{amount if amount != float("inf") else "Infinity"},"date":"{iso()}"}}',
                    content_type="application/json")
    assert r.status_code == 422


# ----------------------------------------------------------------------- CSV
def test_csv_has_bom_and_escapes_formulas(client, cow):
    client.patch(f"/v1/animals/{cow['id']}", json={"name": "=HYPERLINK(\"x\")", "breed": "\tcmd"})
    r = client.get("/v1/reports/herd?format=csv")
    assert r.headers["Content-Type"] == "text/csv; charset=utf-8"
    text = r.get_data(as_text=True)
    assert text.startswith("﻿")
    assert "'=HYPERLINK" in text and "'\tcmd" in text


# --------------------------------------------------------------- reminder job
def test_one_broken_farm_does_not_stop_the_job(make_client, repo, notifier):
    from app.services.reminders import run_due_reminders

    a = make_client("ann")
    a.post("/v1/farms", json={"name": "Farm A", "address": "Road A 12345"})
    b = make_client("bob")
    b.post("/v1/farms", json={"name": "Farm B", "address": "Road B 12345"})
    cow_a = a.post("/v1/animals", json={"ear_tag": "A1", "species": "cattle", "sex": "female"}).json
    cow_b = b.post("/v1/animals", json={"ear_tag": "B1", "species": "cattle", "sex": "female"}).json
    for c, animal in ((a, cow_a), (b, cow_b)):
        c.post("/v1/vaccinations", json={"animal_id": animal["id"], "vaccine_name": "FMD",
                                         "date_given": iso(-10), "next_due_date": iso(1)})
    # Break farm A: a reminder with an unreadable date.
    farm_a = a.get("/v1/me").json["farm"]["id"]
    repo.create(f"farms/{farm_a}/reminders", {"status": "pending", "due_date": "not-a-date", "title": "x"})
    stats = run_due_reminders(repo, notifier)
    assert stats["failed_farms"] == 1 and stats["notified"] >= 1


# ----------------------------------------------------------- account deletion
def test_deleting_an_account_removes_notifications_about_it(make_client, client, repo):
    code = client.get("/v1/farm").json["invite_code"]
    asker = make_client("asker", name="Ali")
    asker.post("/v1/farms/join", json={"invite_code": code})
    farm_id = client.get("/v1/me").json["farm"]["id"]
    assert repo.list(f"farms/{farm_id}/notifications", [("subject_uid", "==", "asker")])
    assert asker.delete("/v1/me").status_code == 204
    assert repo.list(f"farms/{farm_id}/notifications", [("subject_uid", "==", "asker")]) == []


# --------------------------------------------------------------- invite codes
def test_too_many_wrong_invite_codes(make_client):
    c = make_client("guesser")
    for _ in range(10):
        assert c.post("/v1/farms/join", json={"invite_code": "ZZZ-9999"}).status_code == 404
    r = c.post("/v1/farms/join", json={"invite_code": "ZZZ-9999"})
    assert r.status_code == 429 and r.json["code"] == "too_many_attempts"


# --------------------------------------------------------------- farm settings
def test_farm_address_can_be_cleared(client):
    client.patch("/v1/farm", json={"country": "Tunisia"})
    r = client.patch("/v1/farm", json={"country": None, "address": "", "name": None})
    assert r.status_code == 200
    assert r.json["country"] is None and r.json["address"] is None and r.json["name"] == "Green Valley Farm"
