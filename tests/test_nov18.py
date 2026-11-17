"""18 November 2026: admin dashboard (activity, apps, problems, feedback, breed photos, announcements, support)
and the app features (for sale, barn vaccination, weighing session, feed stock, monthly finance summary)."""
from __future__ import annotations

import io
from datetime import date

import pytest

from app.config import get_settings
from tests.test_admin import basic
from tests.test_nov14 import add, expense, farm_client

APP = {"X-Farmivo-Platform": "Android", "X-Farmivo-Version": "1.6.0 (16)", "X-Farmivo-OS": "Android 14",
       "X-Farmivo-Device": "Samsung SM-A155F"}


@pytest.fixture
def admin_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_password", "pw-123")
    monkeypatch.setattr(get_settings(), "admin_allow_remote", False)
    return basic("pw-123")


# ------------------------------------------------------------------------- apps
def test_the_app_version_is_kept_once_an_hour(make_client, repo):
    c = farm_client(make_client)
    c.get("/v1/me", headers=APP)
    user = repo.get("users", "owner1")
    assert user["app_platform"] == "android" and user["app_version"] == "1.6.0 (16)"
    assert user["device_model"] == "Samsung SM-A155F" and user["email"] == "owner1@example.com" and user["last_seen"]
    stamp = user["updated_at"]
    c.get("/v1/me", headers=APP)
    assert repo.get("users", "owner1")["updated_at"] == stamp  # nothing new: not written again
    c.get("/v1/me", headers={**APP, "X-Farmivo-Version": "1.7.0 (17)"})
    assert repo.get("users", "owner1")["app_version"] == "1.7.0 (17)"


def test_app_versions_and_older_ones():
    from app.ops import app_versions, version_key

    assert version_key("1.10.0 (20)") > version_key("1.9.0 (19)")
    users = [{"id": "a", "app_platform": "android", "app_version": "1.6.0 (16)"},
             {"id": "b", "app_platform": "android", "app_version": "1.5.0 (15)"},
             {"id": "c", "app_platform": "ios", "app_version": "1.6.0 (7)"}, {"id": "d"}]
    info = app_versions(users)
    assert info["platforms"] == {"android": 2, "ios": 1, "unknown": 1}
    assert [u["id"] for u in info["old"]] == ["b"] and info["latest"]["android"] == "1.6.0 (16)"


# --------------------------------------------------------------------- problems
def test_a_server_error_is_recorded(make_client, repo, monkeypatch):
    c = farm_client(make_client)
    import app.routers.finance as finance

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(finance, "compute_finance", boom)
    assert c.get("/v1/finance/summary").status_code == 500
    problem = repo.list("problems")[0]
    assert problem["kind"] == "server_error" and "kaboom" in problem["message"] and problem["uid"] == "owner1"
    assert problem["path"] == "/v1/finance/summary" and "RuntimeError" in problem["trace"]


def test_a_failed_email_is_recorded(make_client, repo, mailer):
    mailer.fail = True
    c = make_client("new1", verified=False)
    assert c.post("/v1/me/verification/send").status_code == 502
    p = repo.list("problems")[0]
    assert p["kind"] == "email_failed" and p["email"] == "new1@example.com" and "smtp down" in p["message"]


def test_old_problems_are_pruned(repo, monkeypatch):
    from app import ops

    monkeypatch.setattr(ops.random, "random", lambda: 1.0)  # no pruning by chance inside report()
    repo.create("problems", {"kind": "push_failed", "message": "x", "at": "2020-01-01T00:00:00+00:00"})
    ops.report("push_failed", "y", repo)
    assert ops.prune(repo) == 1 and len(repo.list("problems")) == 1


# --------------------------------------------------------------------- feedback
def test_feedback_with_a_screenshot(make_client, repo, photo_store):
    c = farm_client(make_client)
    r = c.post("/v1/feedback", headers=APP, data={
        "text": "The sale button is hidden", "screen": "Finance",
        "screenshot": (io.BytesIO(b"\x89PNG fake"), "shot.png", "image/png")}, content_type="multipart/form-data")
    assert r.status_code == 201, r.json
    f = repo.get("feedback", r.json["id"])
    assert f["text"] == "The sale button is hidden" and f["screen"] == "Finance" and f["farm_name"]
    assert f["app_version"] == "1.6.0 (16)" and f["screenshot_url"].startswith("https://storage.test/")
    assert c.post("/v1/feedback", json={"text": "  "}).status_code == 422
    assert c.post("/v1/feedback", json={"text": "ok"}).status_code == 201  # JSON works too


def test_feedback_is_limited(make_client):
    c = make_client("u9")  # no farm needed
    for _ in range(10):
        assert c.post("/v1/feedback", json={"text": "hi"}).status_code == 201
    r = c.post("/v1/feedback", json={"text": "hi"}, headers={"Accept-Language": "fr"})
    assert r.status_code == 429 and "heure" in r.json["detail"]


# --------------------------------------------------------------- announcements
def test_an_announcement_reaches_phones_and_the_apps(make_client, repo, notifier, admin_on):
    c = farm_client(make_client)
    c.post("/v1/devices", json={"token": "token-device-0001", "platform": "android"})
    page = c.get("/admin/broadcast", headers=admin_on)
    assert page.status_code == 200
    token = page.data.decode().split('name="token" value="')[1].split('"')[0]
    r = c.post("/admin/broadcast", headers=admin_on, data={
        "token": token, "title_en": "Eid Mubarak", "body_en": "Mark your sheep for sale", "body_fr": "Marquez vos moutons",
        "target": "all"})
    assert r.status_code == 302
    assert notifier.sent and notifier.sent[-1]["data"]["type"] == "announcement"
    shown = c.get("/v1/announcements", headers={"Accept-Language": "fr"}).json
    assert shown and shown[0]["body"] == "Marquez vos moutons" and shown[0]["title"] == "Farmivo"
    assert c.post("/admin/broadcast", headers=admin_on, data={"token": "bad", "body_en": "x"}).status_code == 400


# ---------------------------------------------------------------- admin pages
def test_every_new_admin_page_opens(make_client, repo, admin_on):
    c = farm_client(make_client)
    add(c, "S1")
    expense(c, 50)
    c.post("/v1/feedback", json={"text": "hello"})
    for path in ("/admin", "/admin/activity", "/admin/activity?weeks=52", "/admin/apps", "/admin/problems",
                 "/admin/problems?kind=server_error", "/admin/feedback", "/admin/feedback?show=all", "/admin/breeds",
                 "/admin/breeds?species=goat", "/admin/broadcast", "/admin/users"):
        r = c.get(path, headers=admin_on)
        assert r.status_code == 200, path
    farm_id = c.get("/v1/farm").json["id"]
    for view in ("animals", "barns", "money", "feed"):
        assert c.get(f"/admin/farms/{farm_id}?view={view}", headers=admin_on).status_code == 200


def test_weekly_activity_and_stopped_farms(make_client, repo):
    from app import ops

    c = farm_client(make_client)
    add(c, "S1")
    data = ops.weekly_activity(repo, ops.ACTIVITY_COLLECTIONS, 4)
    assert data["weeks"][-1]["active_farms"] == 1 and data["weeks"][-1]["signups"] >= 1
    farm = repo.list("farms")[0]
    days = {date(2026, 9, 1), date(2026, 9, 3)}
    stopped = ops.stopped_farms([farm], {farm["id"]: days}, today=date(2026, 11, 18))
    assert stopped[0]["quiet_for"] == 76 and stopped[0]["days_used"] == 2


def test_support_resend_code_and_mark_checked(make_client, repo, mailer, admin_on):
    c = make_client("new2", verified=False)
    c.get("/v1/me", headers=APP)  # the email is known from the app
    page = c.get("/admin/users", headers=admin_on).data.decode()
    token = page.split('name="token" value="')[1].split('"')[0]
    r = c.post("/admin/users/new2/resend-code", headers=admin_on, data={"token": token})
    assert r.status_code == 302 and mailer.sent[-1][0] == "new2@example.com"
    assert c.post("/admin/users/new2/mark-verified", headers=admin_on, data={"token": token}).status_code == 302
    assert repo.get("users", "new2")["email_verified"] is True


def test_breed_photo_upload_and_remove(make_client, admin_on, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "breed_photos_dir", str(tmp_path))
    c = make_client("a1")
    page = c.get("/admin/breeds?species=sheep", headers=admin_on).data.decode()
    token = page.split('name="token" value="')[1].split('"')[0]
    from PIL import Image

    raw = io.BytesIO()
    Image.new("RGB", (1600, 1200), (200, 180, 150)).save(raw, "PNG")
    r = c.post("/admin/breeds/upload", headers=admin_on, content_type="multipart/form-data", data={
        "token": token, "species": "sheep", "file": "barbarine", "photo": (io.BytesIO(raw.getvalue()), "b.png", "image/png")})
    assert r.status_code == 302
    saved = tmp_path / "sheep" / "barbarine.jpg"
    assert saved.read_bytes()[:2] == b"\xff\xd8" and Image.open(saved).size[0] <= 960
    assert c.get("/v1/breeds/photo/sheep/barbarine.jpg").status_code == 200
    assert c.post("/admin/breeds/upload", headers=admin_on, data={"token": token, "species": "sheep", "file": "../x"}).status_code == 404
    assert c.post("/admin/breeds/remove", headers=admin_on, data={"token": token, "species": "sheep",
                                                                  "file": "barbarine"}).status_code == 302
    assert not saved.exists()


# ------------------------------------------------------------------- for sale
def test_animals_for_sale_with_their_last_weight(make_client):
    c = farm_client(make_client)
    a = add(c, "S1", for_sale=True, asking_price=1200, sale_note="Eid sheep")
    add(c, "S2")
    c.post("/v1/weights", json={"animal_id": a["id"], "date": "2026-11-01", "weight_kg": 41})
    c.post("/v1/weights", json={"animal_id": a["id"], "date": "2026-11-10", "weight_kg": 44.5})
    listed = c.get("/v1/animals?for_sale=true").json
    assert [x["ear_tag"] for x in listed] == ["S1"] and listed[0]["asking_price"] == 1200
    assert listed[0]["latest_weight_kg"] == 44.5 and listed[0]["latest_weight_date"] == "2026-11-10"
    assert c.get(f"/v1/animals/{a['id']}").json["latest_weight_kg"] == 44.5
    c.post(f"/v1/animals/{a['id']}/status", json={"status": "sold", "sale_price": 1150})
    assert c.get("/v1/animals?for_sale=true").json == []
    assert c.get(f"/v1/animals/{a['id']}").json["for_sale"] is False


# ------------------------------------------------------------- work on a barn
def test_vaccinate_a_whole_barn(make_client):
    c = farm_client(make_client)
    barn = c.post("/v1/barns", json={"name": "Fold", "species_list": ["sheep", "goat"]}).json
    ids = [add(c, f"S{n}", barn_id=barn["id"])["id"] for n in range(3)]
    add(c, "G1", species="goat", barn_id=barn["id"])
    c.post(f"/v1/animals/{ids[2]}/status", json={"status": "deceased"})
    r = c.post("/v1/vaccinations/bulk", json={"barn_id": barn["id"], "species": "sheep", "vaccine_name": "Enterotoxemia",
                                              "date_given": "2026-11-15", "next_due_date": "2027-05-15"})
    assert r.status_code == 201 and r.json == {"created": 2, "skipped": 0}  # the dead one left the barn
    vaccinated = {v["animal_id"] for v in c.get("/v1/vaccinations").json}
    assert vaccinated == set(ids[:2])
    assert len([x for x in c.get("/v1/reminders").json if x.get("source_type") == "vaccination"]) == 2
    assert c.post("/v1/vaccinations/bulk", json={"vaccine_name": "X", "date_given": "2026-11-15"}).status_code == 422


def test_weighing_session(make_client):
    c = farm_client(make_client)
    a, b = add(c, "S1"), add(c, "S2")
    r = c.post("/v1/weights/bulk", json={"date": "2026-11-12", "entries": [
        {"animal_id": a["id"], "weight_kg": 40}, {"animal_id": b["id"], "weight_kg": 38.5}]})
    assert r.status_code == 201 and r.json["created"] == 2
    assert {w["weight_kg"] for w in c.get("/v1/weights").json} == {40, 38.5}
    assert c.post("/v1/weights/bulk", json={"entries": [{"animal_id": "nope", "weight_kg": 3}]}).status_code == 404


def test_select_several_and_move_them(make_client):
    c = farm_client(make_client)
    barn = c.post("/v1/barns", json={"name": "B", "species": "sheep"}).json
    ids = [add(c, f"S{n}")["id"] for n in range(3)]
    assert c.post("/v1/animals/move", json={"animal_ids": ids, "barn_id": barn["id"]}).json["moved"] == 3


# ------------------------------------------------------------------- feed stock
def test_feed_stock_books_the_expense_and_warns_when_low(make_client, notifier):
    c = farm_client(make_client)
    c.post("/v1/devices", json={"token": "token-device-0001", "platform": "android"})
    add(c, "S1")
    barley = c.post("/v1/feed-stock/items", json={"name": "Barley", "sack_kg": 50, "low_at": 3}).json
    bought = c.post("/v1/feed-stock/moves", json={"feed_id": barley["id"], "direction": "in", "sacks": 10,
                                                  "unit_price": 45, "date": "2026-11-10", "supplier": "Coop"}).json
    assert bought["amount"] == 450 and bought["transaction_id"]
    tx = c.get(f"/v1/transactions/{bought['transaction_id']}").json
    assert tx["category"] == "feed" and tx["amount"] == 450 and "Barley" in tx["description"]
    assert c.post("/v1/feed-stock/moves", json={"feed_id": barley["id"], "direction": "out", "sacks": 11}).status_code == 422
    out = c.post("/v1/feed-stock/moves", json={"feed_id": barley["id"], "direction": "out", "sacks": 7}).json
    assert "Barley, 3 sacks left" in out["notice"]
    assert [n["data"]["type"] for n in notifier.sent].count("feed_low") == 1
    c.post("/v1/feed-stock/moves", json={"feed_id": barley["id"], "direction": "out", "sacks": 1})
    assert [n["data"]["type"] for n in notifier.sent].count("feed_low") == 1  # once, when it crossed the line
    stock = c.get("/v1/feed-stock").json
    assert stock[0]["balance"] == 2 and stock[0]["low"] is True
    # editing the purchase changes the expense; deleting it deletes the expense
    c.patch(f"/v1/feed-stock/moves/{bought['id']}", json={"sacks": 12})
    assert c.get(f"/v1/transactions/{bought['transaction_id']}").json["amount"] == 540
    c.delete(f"/v1/feed-stock/moves/{out['id']}")
    c.delete(f"/v1/feed-stock/moves/{bought['id']}")
    assert c.get(f"/v1/transactions/{bought['transaction_id']}").status_code == 404


def test_feed_expense_deleted_in_finance_unlinks_the_purchase(make_client):
    c = farm_client(make_client)
    hay = c.post("/v1/feed-stock/items", json={"name": "Hay"}).json
    m = c.post("/v1/feed-stock/moves", json={"feed_id": hay["id"], "direction": "in", "sacks": 4, "unit_price": 10}).json
    assert c.delete(f"/v1/transactions/{m['transaction_id']}").status_code == 204
    assert c.get(f"/v1/feed-stock/moves/{m['id']}").json["transaction_id"] is None
    assert c.get("/v1/feed-stock").json[0]["balance"] == 4


def test_workers_record_sacks_but_not_prices(make_client):
    owner = farm_client(make_client)
    code = owner.get("/v1/farm").json["invite_code"]
    worker = make_client("w1")
    worker.post("/v1/farms/join", json={"invite_code": code})
    owner.post("/v1/farm/members/w1/approve", json={"role": "worker"})
    hay = owner.post("/v1/feed-stock/items", json={"name": "Hay"}).json
    owner.post("/v1/feed-stock/moves", json={"feed_id": hay["id"], "direction": "in", "sacks": 5, "unit_price": 10})
    assert worker.post("/v1/feed-stock/moves", json={"feed_id": hay["id"], "direction": "in", "sacks": 1,
                                                     "unit_price": 9}).status_code == 403
    assert worker.post("/v1/feed-stock/moves", json={"feed_id": hay["id"], "direction": "out", "sacks": 1}).status_code == 201
    moves = worker.get("/v1/feed-stock/moves").json
    assert all(m["unit_price"] is None and m["amount"] is None for m in moves)


# ---------------------------------------------------------- monthly summary
def test_monthly_finance_summary_page(make_client):
    c = farm_client(make_client)
    expense(c, 300, "feed", date="2026-10-05")
    expense(c, 120, "veterinary", date="2026-10-20")
    c.post("/v1/transactions", json={"type": "income", "category": "milk_sale", "amount": 900, "date": "2026-10-28"})
    expense(c, 50, "feed", date="2026-09-03")
    r = c.get("/v1/finance/month-report?month=2026-10")
    page = r.data.decode()
    assert r.status_code == 200 and r.content_type.startswith("text/html")
    assert "October 2026" in page and "900" in page and "420" in page and "480" in page and "Veterinary" in page
    ar = c.get("/v1/finance/month-report?month=2026-10", headers={"Accept-Language": "ar"}).data.decode()
    assert 'dir="rtl"' in ar and "أكتوبر 2026" in ar and "البيطرة" in ar
    assert c.get("/v1/finance/month-report?month=2026-13").status_code == 422
