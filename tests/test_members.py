"""Farm membership: create or join a farm, approval, roles, permissions, ownership and legacy accounts."""
import pytest

from app.permissions import required_role
from app.services.membership import code_prefix, normalize_code

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}


def invite_code(owner):
    return owner.get("/v1/farm").json["invite_code"]


def join(make_client, owner, uid, role="worker"):
    """Create a client for ``uid``, ask to join the owner's farm and get approved with ``role``."""
    c = make_client(uid, name=uid.title())
    assert c.post("/v1/farms/join", json={"invite_code": invite_code(owner)}).status_code == 200
    r = owner.post(f"/v1/farm/members/{uid}/approve", json={"role": role})
    assert r.status_code == 200, r.text
    return c


# ------------------------------------------------------------------ onboarding

def test_new_user_has_no_farm_and_no_auto_creation(make_client, repo):
    c = make_client("new")
    me = c.get("/v1/me").json
    assert me == {"uid": "new", "email": "new@example.com", "status": "none", "role": None, "farm": None}
    r = c.get("/v1/animals")
    assert r.status_code == 403 and r.json["code"] == "no_farm"
    assert repo.list("farms") == []


def test_create_farm_makes_owner(make_client):
    c = make_client("u1")
    r = c.post("/v1/farms", json={**FARM, "currency": "tnd"})
    assert r.status_code == 201
    assert r.json["status"] == "active" and r.json["role"] == "owner" and r.json["farm"]["name"] == FARM["name"]
    farm = c.get("/v1/farm").json
    assert farm["role"] == "owner" and farm["currency"] == "TND" and farm["invite_code"].startswith("GVF-")
    assert c.post("/v1/farms", json=FARM).status_code == 409


def test_create_farm_validation(make_client):
    c = make_client("u1")
    assert c.post("/v1/farms", json={"name": "X", "address": "Somewhere 1"}).status_code == 422
    assert c.post("/v1/farms", json={"name": "Farm", "address": "abc"}).status_code == 422


def test_join_flow_pending_then_approved(client, make_client, notifier, repo):
    # the owner's phone is registered, so the join request is pushed to it
    client.post("/v1/devices", json={"token": "owner-token-123", "platform": "android"})
    w = make_client("worker-1", name="Ali")
    w.post("/v1/devices", json={"token": "worker-token-123", "platform": "ios"})  # allowed before approval
    code = invite_code(client)
    r = w.post("/v1/farms/join", json={"invite_code": code.lower().replace("-", " ")})
    assert r.status_code == 200 and r.json["status"] == "pending" and r.json["role"] is None
    assert r.json["farm"]["name"] == FARM["name"]
    blocked = w.get("/v1/animals")
    assert blocked.status_code == 403 and blocked.json["code"] == "pending"
    assert "waiting for approval" in blocked.json["detail"]
    # owner sees the request and was notified
    members = client.get("/v1/farm/members").json
    assert [m["uid"] for m in members] == ["worker-1", "user-1"] and members[0]["status"] == "pending"
    assert notifier.sent[-1]["tokens"] == ["owner-token-123"] and "Ali wants to join" in notifier.sent[-1]["title"]
    assert any(n["type"] == "join_request" for n in client.get("/v1/notifications").json)
    # approve: default role worker, push to the new member
    approved = client.post("/v1/farm/members/worker-1/approve")
    assert approved.status_code == 200 and approved.json["role"] == "worker" and approved.json["status"] == "active"
    assert notifier.sent[-1]["tokens"] == ["worker-token-123"]
    me = w.get("/v1/me").json
    assert me["status"] == "active" and me["role"] == "worker"
    assert w.get("/v1/animals").status_code == 200


def test_join_unknown_code_and_already_member(client, make_client):
    c = make_client("x")
    r = c.post("/v1/farms/join", json={"invite_code": "ZZZ-2222"})
    assert r.status_code == 404 and r.json["detail"] == "No farm with this code"
    assert client.post("/v1/farms/join", json={"invite_code": invite_code(client)}).status_code == 409


def test_reject_then_ask_again_or_create_own(client, make_client, repo):
    c = make_client("x")
    c.post("/v1/farms/join", json={"invite_code": invite_code(client)})
    assert client.post("/v1/farm/members/x/reject").json["status"] == "rejected"
    me = c.get("/v1/me").json
    assert me["status"] == "rejected" and me["farm"]["name"] == FARM["name"]
    r = c.get("/v1/animals")
    assert r.status_code == 403 and r.json["code"] == "rejected"
    assert [m["uid"] for m in client.get("/v1/farm/members").json] == ["user-1"]  # rejected are not listed
    assert c.post("/v1/farms/join", json={"invite_code": invite_code(client)}).json["status"] == "pending"
    c.delete("/v1/me/membership")
    assert c.post("/v1/farms", json={"name": "Own Farm", "address": "Road 12, Tunis"}).status_code == 201


def test_pending_can_cancel_and_switch_farm(client, make_client):
    other_owner = make_client("o2")
    other_owner.post("/v1/farms", json={"name": "Hill Farm", "address": "Road 3, Beja"})
    c = make_client("x")
    c.post("/v1/farms/join", json={"invite_code": invite_code(client)})
    r = c.post("/v1/farms/join", json={"invite_code": invite_code(other_owner)})
    assert r.json["farm"]["name"] == "Hill Farm"
    assert [m["uid"] for m in client.get("/v1/farm/members").json] == ["user-1"]  # old request replaced
    assert c.delete("/v1/me/membership").json["status"] == "none"
    assert [m["uid"] for m in other_owner.get("/v1/farm/members").json] == ["o2"]


def test_create_farm_while_pending_is_refused(client, make_client):
    c = make_client("x")
    c.post("/v1/farms/join", json={"invite_code": invite_code(client)})
    assert c.post("/v1/farms", json=FARM).status_code == 409


# ------------------------------------------------------------------ permissions

def test_viewer_reads_but_cannot_write_or_see_finance(client, make_client, cow):
    v = join(make_client, client, "viewer-1", "viewer")
    assert v.get("/v1/animals").status_code == 200
    assert v.get(f"/v1/animals/{cow['id']}").status_code == 200
    r = v.post("/v1/animals", json={"ear_tag": "V1", "species": "goat", "sex": "male"})
    assert r.status_code == 403 and r.json["code"] == "forbidden_role"
    assert v.get("/v1/transactions").status_code == 403
    assert v.get("/v1/finance/summary").status_code == 403
    assert v.get("/v1/reports/financial").status_code == 403
    assert v.get("/v1/reports/herd").status_code == 200
    dash = v.get("/v1/dashboard")
    assert dash.status_code == 200 and dash.json["finance"] is None
    assert v.post("/v1/notifications/read-all").status_code == 204
    farm = v.get("/v1/farm").json
    assert farm["role"] == "viewer" and farm["invite_code"] is None
    assert v.get("/v1/farm/members").status_code == 403


def test_worker_writes_but_cannot_delete_or_manage(client, make_client, cow):
    w = join(make_client, client, "worker-1", "worker")
    r = w.post("/v1/animals", json={"ear_tag": "W1", "species": "sheep", "sex": "female"})
    assert r.status_code == 201
    assert w.patch(f"/v1/animals/{cow['id']}", json={"breed": "Holstein"}).status_code == 200
    vac = w.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD", "date_given": "2026-01-01"})
    assert vac.status_code == 201
    assert w.delete(f"/v1/animals/{r.json['id']}").status_code == 403
    assert w.delete(f"/v1/vaccinations/{vac.json['id']}").status_code == 403
    assert w.patch("/v1/farm", json={"name": "Mine now"}).status_code == 403
    assert w.post("/v1/transactions", json={"type": "expense", "category": "feed", "amount": 5,
                                             "date": "2026-01-01"}).status_code == 403
    assert w.get("/v1/dashboard").json["finance"] is None
    assert w.post("/v1/farm/invite-code").status_code == 403


def test_manager_manages_members_and_sees_finance(client, make_client, cow):
    m = join(make_client, client, "manager-1", "manager")
    assert m.get("/v1/dashboard").json["finance"] is not None
    assert m.get("/v1/finance/summary").status_code == 200
    assert m.get("/v1/farm").json["invite_code"]
    w = make_client("w2")
    w.post("/v1/farms/join", json={"invite_code": m.get("/v1/farm").json["invite_code"]})
    assert m.post("/v1/farm/members/w2/approve", json={"role": "viewer"}).json["role"] == "viewer"
    assert m.patch("/v1/farm/members/w2", json={"role": "worker"}).json["role"] == "worker"
    assert m.delete(f"/v1/animals/{cow['id']}").status_code == 204
    # the owner is protected
    assert m.patch("/v1/farm/members/user-1", json={"role": "worker"}).status_code == 409
    assert m.delete("/v1/farm/members/user-1").status_code == 409
    assert m.post("/v1/farm/transfer-ownership", json={"uid": "manager-1"}).status_code == 403
    # role "owner" cannot be given by PATCH or approve
    assert m.patch("/v1/farm/members/w2", json={"role": "owner"}).status_code == 422
    assert m.delete("/v1/farm/members/w2").status_code == 204
    assert w.get("/v1/me").json["status"] == "none"


def test_role_change_takes_effect_on_next_request(client, make_client):
    w = join(make_client, client, "w1", "viewer")
    assert w.post("/v1/animals", json={"ear_tag": "Z", "species": "goat", "sex": "male"}).status_code == 403
    client.patch("/v1/farm/members/w1", json={"role": "worker"})
    assert w.post("/v1/animals", json={"ear_tag": "Z", "species": "goat", "sex": "male"}).status_code == 201


def test_removed_member_loses_access(client, make_client):
    w = join(make_client, client, "w1")
    assert client.delete("/v1/farm/members/w1").status_code == 204
    r = w.get("/v1/animals")
    assert r.status_code == 403 and r.json["code"] == "no_farm"


def test_invite_code_rotation(client, make_client):
    old = invite_code(client)
    new = client.post("/v1/farm/invite-code").json["invite_code"]
    assert new != old and invite_code(client) == new
    c = make_client("x")
    assert c.post("/v1/farms/join", json={"invite_code": old}).status_code == 404
    assert c.post("/v1/farms/join", json={"invite_code": new}).status_code == 200


def test_transfer_ownership(client, make_client):
    m = join(make_client, client, "m1", "manager")
    assert client.post("/v1/farm/transfer-ownership", json={"uid": "user-1"}).status_code == 409
    r = client.post("/v1/farm/transfer-ownership", json={"uid": "m1"})
    assert r.status_code == 200 and r.json["role"] == "owner"
    assert client.get("/v1/me").json["role"] == "manager"
    assert m.get("/v1/farm").json["owner_uid"] == "m1"
    roles = {x["uid"]: x["role"] for x in m.get("/v1/farm/members").json}
    assert list(roles.values()).count("owner") == 1


def test_owner_cannot_leave_but_member_can(client, make_client):
    r = client.delete("/v1/me/membership")
    assert r.status_code == 409 and r.json["detail"] == "Transfer ownership first"
    w = join(make_client, client, "w1")
    assert w.delete("/v1/me/membership").json["status"] == "none"
    assert [x["uid"] for x in client.get("/v1/farm/members").json] == ["user-1"]


def test_approve_requires_pending(client, make_client):
    join(make_client, client, "w1")
    assert client.post("/v1/farm/members/w1/approve").status_code == 409
    assert client.post("/v1/farm/members/nobody/approve").status_code == 404


def test_reminder_pushes_only_go_to_active_members(client, make_client, repo, notifier, cow):
    from app.services.reminders import run_due_reminders

    client.post("/v1/devices", json={"token": "owner-token-123", "platform": "android"})
    p = make_client("pending-1")
    p.post("/v1/devices", json={"token": "pending-token-123", "platform": "android"})
    p.post("/v1/farms/join", json={"invite_code": invite_code(client)})
    from datetime import date, timedelta
    client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD",
                                          "date_given": "2026-01-01",
                                          "next_due_date": (date.today() + timedelta(days=1)).isoformat()})
    notifier.sent.clear()
    run_due_reminders(repo, notifier)
    assert notifier.sent and all("pending-token-123" not in s["tokens"] for s in notifier.sent)
    assert any("owner-token-123" in s["tokens"] for s in notifier.sent)


# ------------------------------------------------------------------ legacy accounts

def test_legacy_owner_becomes_active_owner_with_invite_code(make_client, repo):
    repo.create("farms", {"name": "Old Farm", "currency": "USD", "owner_uid": "legacy", "member_uids": ["legacy"]},
                doc_id="f-old")
    repo.set("users", "legacy", {"farm_id": "f-old"})
    c = make_client("legacy")
    me = c.get("/v1/me").json
    assert me["status"] == "active" and me["role"] == "owner" and me["farm"]["id"] == "f-old"
    farm = c.get("/v1/farm").json
    assert farm["invite_code"].startswith("OLD")
    assert c.get("/v1/animals").status_code == 200


def test_user_pointing_at_someone_elses_farm_is_not_upgraded(make_client, repo):
    repo.create("farms", {"name": "Old Farm", "owner_uid": "legacy"}, doc_id="f-old")
    repo.set("users", "intruder", {"farm_id": "f-old"})
    assert make_client("intruder").get("/v1/me").json["status"] == "none"


# ------------------------------------------------------------------ helpers

@pytest.mark.parametrize("method,path,role", [
    ("GET", "/v1/animals", "viewer"),
    ("POST", "/v1/animals", "worker"),
    ("PATCH", "/v1/animals/1", "worker"),
    ("DELETE", "/v1/animals/1", "manager"),
    ("POST", "/v1/notifications/1/read", "viewer"),
    ("POST", "/v1/notifications/read-all", "viewer"),
    ("DELETE", "/v1/notifications/1", "worker"),
    ("GET", "/v1/transactions", "manager"),
    ("GET", "/v1/finance/summary", "manager"),
    ("GET", "/v1/reports/financial", "manager"),
    ("GET", "/v1/reports/herd", "viewer"),
    ("GET", "/v1/farm", "viewer"),
    ("PATCH", "/v1/farm", "manager"),
    ("GET", "/v1/farm/members", "manager"),
    ("POST", "/v1/farm/invite-code", "manager"),
    ("POST", "/v1/farm/transfer-ownership", "owner"),
    ("POST", "/v1/reminders/1/done", "worker"),
    ("DELETE", "/v1/reminders/1", "manager"),
])
def test_permission_policy(method, path, role):
    assert required_role(method, path) == role


def test_code_helpers():
    assert code_prefix("Green Valley Farm") == "GVF"
    assert code_prefix("My Farm") == "MYF"
    assert code_prefix("مزرعة") == "FRM"
    assert normalize_code(" gvf 7k3p ") == "GVF-7K3P"
    assert normalize_code("GVF-7K3P") == "GVF-7K3P"
