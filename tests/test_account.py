"""Account deletion (DELETE /v1/me) and the public legal pages (/privacy, /terms, /support, /delete-account)."""
import io

import pytest

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}


def invite_code(owner):
    return owner.get("/v1/farm").json["invite_code"]


def ask_to_join(make_client, owner, uid):
    c = make_client(uid, name=uid.title())
    assert c.post("/v1/farms/join", json={"invite_code": invite_code(owner)}).status_code == 200
    return c


def join(make_client, owner, uid, role="worker"):
    c = ask_to_join(make_client, owner, uid)
    assert owner.post(f"/v1/farm/members/{uid}/approve", json={"role": role}).status_code == 200
    return c


def all_farm_records(repo, farm_id):
    from app.repository import farm_path
    from app.services.account import FARM_COLLECTIONS

    return {c: repo.list(farm_path(farm_id, c)) for c in FARM_COLLECTIONS if repo.list(farm_path(farm_id, c))}


# ------------------------------------------------------------------ DELETE /v1/me

def test_member_deletes_account_keeps_farm(make_client, client, repo, auth_admin):
    worker = join(make_client, client, "w1")
    worker.post("/v1/devices", json={"token": "w" * 20, "platform": "android"})
    farm_id = client.get("/v1/farm").json["id"]

    r = worker.delete("/v1/me")
    assert r.status_code == 204 and r.data == b""
    assert auth_admin.deleted == ["w1"]
    assert repo.get("users", "w1") is None
    assert repo.list("users/w1/devices") == []
    assert all(m["uid"] != "w1" for m in client.get("/v1/farm/members").json)
    assert repo.get("farms", farm_id) is not None  # the farm stays for the owner
    assert make_client("w1").get("/v1/me").json["status"] == "none"


def test_pending_requester_deletes_account(make_client, client, repo, auth_admin):
    asker = ask_to_join(make_client, client, "p1")
    assert asker.delete("/v1/me").status_code == 204
    assert all(m["uid"] != "p1" for m in client.get("/v1/farm/members").json)
    assert repo.get("users", "p1") is None and auth_admin.deleted == ["p1"]


def test_user_without_farm_can_delete(make_client, repo, auth_admin):
    c = make_client("lonely", verified=False)
    c.post("/v1/me/verification/send")
    assert repo.get("email_codes", "lonely") is not None
    assert c.delete("/v1/me").status_code == 204
    assert repo.get("email_codes", "lonely") is None and auth_admin.deleted == ["lonely"]


def test_owner_alone_deletes_whole_farm(make_client, client, cow, repo, auth_admin, photo_store):
    farm_id = client.get("/v1/farm").json["id"]
    client.post(f"/v1/animals/{cow['id']}/photo",
                data={"file": (io.BytesIO(b"\xff\xd8data"), "a.jpg", "image/jpeg")}, content_type="multipart/form-data")
    client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD",
                                          "date_given": "2026-01-01", "next_due_date": "2027-01-01"})
    client.post("/v1/weights", json={"animal_id": cow["id"], "date": "2026-01-01", "weight_kg": 300})
    client.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 10, "date": "2026-01-01"})
    asker = ask_to_join(make_client, client, "p2")  # a pending request is dropped with the farm
    assert photo_store.files and all_farm_records(repo, farm_id)

    assert client.delete("/v1/me").status_code == 204
    assert repo.get("farms", farm_id) is None
    assert all_farm_records(repo, farm_id) == {}
    assert photo_store.files == {}
    assert repo.get("users", "user-1") is None and auth_admin.deleted == ["user-1"]
    assert asker.get("/v1/me").json["status"] == "none"


def test_owner_with_active_members_must_transfer(make_client, client, repo, auth_admin):
    join(make_client, client, "m1", role="manager")
    r = client.delete("/v1/me")
    assert r.status_code == 409 and r.json["code"] == "owner_must_transfer"
    assert r.json["detail"] == "Transfer ownership before deleting your account"
    assert auth_admin.deleted == [] and client.get("/v1/me").json["role"] == "owner"
    fr = client.delete("/v1/me", headers={"Accept-Language": "fr"})
    assert fr.json["detail"].startswith("Transférez la propriété")
    ar = client.delete("/v1/me", headers={"Accept-Language": "ar"})
    assert "انقل ملكية المزرعة" in ar.json["detail"]


def test_owner_can_delete_after_transfer(make_client, client, repo, auth_admin):
    manager = join(make_client, client, "m2", role="manager")
    assert client.post("/v1/farm/transfer-ownership", json={"uid": "m2"}).status_code == 200
    assert client.delete("/v1/me").status_code == 204
    assert manager.get("/v1/me").json["role"] == "owner"
    assert all(m["uid"] != "user-1" for m in manager.get("/v1/farm/members").json)


def test_firebase_failure_does_not_fail_the_request(make_client, client, auth_admin):
    def boom(uid):
        raise RuntimeError("firebase down")

    auth_admin.delete_user = boom
    assert client.delete("/v1/me").status_code == 204


def test_delete_requires_sign_in():
    from app.main import create_app

    r = create_app().test_client().delete("/v1/me")
    assert r.status_code == 401


# ------------------------------------------------------------------ public pages

@pytest.mark.parametrize("page", ["terms", "delete-account"])
@pytest.mark.parametrize("lang", ["en", "fr", "ar"])
def test_public_pages_in_each_language(page, lang):
    from app.main import create_app

    c = create_app().test_client()
    r = c.get(f"/{page}?lang={lang}")
    assert r.status_code == 200 and r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert f'lang="{lang}"' in html
    assert ('dir="rtl"' in html) == (lang == "ar")
    assert "contact@quadralens.tn" in html and "Farmivo" in html
    for other in ("en", "fr", "ar"):
        assert f"?lang={other}" in html  # language switch


def test_public_page_language_from_header():
    from app.main import create_app

    c = create_app().test_client()
    assert 'lang="fr"' in c.get("/terms", headers={"Accept-Language": "fr-FR,fr;q=0.9"}).get_data(as_text=True)
    assert 'lang="en"' in c.get("/terms?lang=xx").get_data(as_text=True)


def test_support_redirects_to_the_product_page():
    from app.main import create_app

    r = create_app().test_client().get("/support?lang=fr")
    assert r.status_code == 301 and r.headers["Location"] == "https://quadralens.tn/product/farmivo/"


def test_privacy_redirects_to_the_official_page():
    from app.main import create_app

    r = create_app().test_client().get("/privacy?lang=ar")
    assert r.status_code == 301 and r.headers["Location"] == "https://quadralens.tn/product/farmivo-privacy/"
