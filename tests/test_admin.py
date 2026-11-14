"""Admin web dashboard (/admin)."""
import base64

import pytest

from app.config import get_settings

FARM = {"name": "Green <b>Valley</b>", "address": "Route de Mateur, Bizerte"}


def basic(password, user="admin"):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def admin(make_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_password", "pw-123")
    monkeypatch.setattr(get_settings(), "admin_allow_remote", False)
    owner = make_client("owner1", name="Owner")
    assert owner.post("/v1/farms", json=FARM).status_code == 201
    owner.post("/v1/animals", json={"ear_tag": "1", "species": "sheep", "sex": "female"})
    return owner


def test_off_without_password(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_password", None)
    assert client.get("/admin", headers=basic("x")).status_code == 404


def test_password_and_local_only(admin):
    assert admin.get("/admin").status_code == 401
    assert admin.get("/admin", headers=basic("wrong")).status_code == 401
    assert admin.get("/admin", headers=basic("pw-123", user="root")).status_code == 401
    r = admin.get("/admin", headers=basic("pw-123"))
    assert r.status_code == 200 and b"Animals on farms" in r.data
    assert b"<b>Valley</b>" not in r.data and b"&lt;b&gt;Valley" in r.data  # names are escaped
    assert admin.get("/admin", headers={**basic("pw-123"), "X-Forwarded-For": "8.8.8.8"}).status_code == 404
    assert admin.get("/admin", headers=basic("pw-123"), environ_base={"REMOTE_ADDR": "8.8.8.8"}).status_code == 404


def test_pages_and_delete(admin, repo):
    farm_id = admin.get("/v1/farm").json["id"]
    h = basic("pw-123")
    assert b"owner1@example.com" in admin.get("/admin/farms?q=owner1", headers=h).data
    assert b"No farm." in admin.get("/admin/farms?q=nothing", headers=h).data
    page = admin.get(f"/admin/farms/{farm_id}", headers=h).data.decode()
    assert "Delete this farm" in page and "owner1@example.com" in page
    assert b"owner1@example.com" in admin.get("/admin/users", headers=h).data
    token = page.split('name="token" value="')[1].split('"')[0]
    assert admin.post(f"/admin/farms/{farm_id}/delete", headers=h, data={"token": "x", "confirm": FARM["name"]}).status_code == 400
    assert admin.post(f"/admin/farms/{farm_id}/delete", headers=h, data={"token": token, "confirm": "Green"}).status_code == 400
    assert repo.get("farms", farm_id)
    r = admin.post(f"/admin/farms/{farm_id}/delete", headers=h, data={"token": token, "confirm": FARM["name"]})
    assert r.status_code == 302 and repo.get("farms", farm_id) is None
