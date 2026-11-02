"""Membership state across sign-out and sign-in: /v1/me must always reflect the member record.

A "session" is a new test client for the same uid sharing the database, like signing in again on a phone.
Sign-out only calls DELETE /v1/devices; nothing about the farm may change.
"""
from app.services.membership import members_path

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}
HDR = {"Accept-Language": "fr"}


def me(make_client, uid):
    """GET /v1/me from a fresh session (new client, same user), sending a language like the apps do."""
    return make_client(uid).get("/v1/me", headers=HDR).json


def sign_out(c, token):
    assert c.delete(f"/v1/devices?token={token}").status_code == 204


def code_of(owner):
    return owner.get("/v1/farm").json["invite_code"]


def test_owner_stays_active_after_sign_out_and_in(make_client):
    owner = make_client("own")
    owner.post("/v1/devices", json={"token": "tok-owner-1234", "platform": "android", "language": "fr"})
    assert owner.post("/v1/farms", json=FARM).status_code == 201
    sign_out(owner, "tok-owner-1234")
    for _ in range(3):
        m = me(make_client, "own")
        assert (m["status"], m["role"], m["farm"]["name"]) == ("active", "owner", FARM["name"])


def test_joined_member_active_again_after_relogin(make_client):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    w = make_client("w"); w.post("/v1/devices", json={"token": "tok-worker-1234", "platform": "android"})
    assert w.post("/v1/farms/join", json={"invite_code": code_of(owner)}).json["status"] == "pending"
    assert me(make_client, "w")["status"] == "pending"
    assert owner.post("/v1/farm/members/w/approve", json={"role": "worker"}).status_code == 200
    assert me(make_client, "w")["status"] == "active"
    sign_out(w, "tok-worker-1234")
    m = me(make_client, "w")
    assert (m["status"], m["role"]) == ("active", "worker")
    assert make_client("w").get("/v1/animals").status_code == 200


def test_reject_remove_leave(make_client):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    r = make_client("r"); r.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/r/reject")
    assert me(make_client, "r")["status"] == "rejected"

    x = make_client("x"); x.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/x/approve", json={"role": "viewer"})
    assert owner.delete("/v1/farm/members/x").status_code == 204
    assert me(make_client, "x")["status"] == "none"

    y = make_client("y"); y.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/y/approve")
    assert y.delete("/v1/me/membership").json["status"] == "none"
    assert me(make_client, "y")["status"] == "none"


def test_transfer_ownership_survives_relogin(make_client):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    m = make_client("m"); m.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/m/approve", json={"role": "manager"})
    assert owner.post("/v1/farm/transfer-ownership", json={"uid": "m"}).status_code == 200
    a, b = me(make_client, "own"), me(make_client, "m")
    assert (a["status"], a["role"]) == ("active", "manager")
    assert (b["status"], b["role"]) == ("active", "owner")


def test_legacy_auto_created_farm(make_client, repo):
    repo.create("farms", {"name": "Old Farm", "currency": "USD", "owner_uid": "old", "member_uids": ["old"]},
                doc_id="f-old")
    repo.set("users", "old", {"farm_id": "f-old"})
    m = me(make_client, "old")
    assert (m["status"], m["role"], m["farm"]["id"]) == ("active", "owner", "f-old")
    assert me(make_client, "old")["status"] == "active"


def test_member_record_is_the_source_of_truth(make_client, repo):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    farm_id = repo.get("users", "own")["farm_id"]
    # users says pending, member says active -> active, and the users doc is healed
    repo.update("users", "own", {"status": "pending"})
    assert me(make_client, "own")["status"] == "active"
    assert repo.get("users", "own")["status"] == "active"
    # users doc lost entirely (or lost farm_id) -> found through the member record
    repo.delete("users", "own")
    m = me(make_client, "own")
    assert (m["status"], m["role"], m["farm"]["id"]) == ("active", "owner", farm_id)
    assert repo.get("users", "own")["farm_id"] == farm_id
    repo.update("users", "own", {"farm_id": None})
    assert me(make_client, "own")["status"] == "active"
    # users points at a farm without a member record, but the member record exists in another farm
    repo.update("users", "own", {"farm_id": "missing-farm"})
    assert me(make_client, "own")["farm"]["id"] == farm_id


def test_verification_and_language_do_not_drop_the_farm(make_client, repo, mailer):
    c = make_client("v", verified=False)
    c.post("/v1/me/verification/send", headers=HDR)
    assert c.post("/v1/me/verification/verify", json={"code": mailer.last_code}).status_code == 200
    assert c.post("/v1/farms", json=FARM).status_code == 201
    for lang in ("ar", "en", "fr"):
        make_client("v").get("/v1/me", headers={"Accept-Language": lang})
    user = repo.get("users", "v")
    assert user["farm_id"] and user["status"] == "active" and user["email_verified"] is True
    assert me(make_client, "v")["status"] == "active"


def test_devices_never_touch_membership(make_client, repo):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    before = repo.get(members_path(repo.get("users", "own")["farm_id"]), "own")
    owner.post("/v1/devices", json={"token": "tok-a-123456", "platform": "ios"})
    owner.delete("/v1/devices?token=tok-a-123456")
    owner.delete("/v1/devices?token=never-registered-1")
    after = repo.get(members_path(repo.get("users", "own")["farm_id"]), "own")
    assert before["status"] == after["status"] == "active" and before["role"] == after["role"]


# ------------------------------------------------------------------ notifications from pushes

def test_push_data_carries_notification_id_and_tap_marks_it_read(make_client, notifier):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    owner.post("/v1/devices", json={"token": "tok-owner-1234", "platform": "android"})
    w = make_client("w"); w.post("/v1/devices", json={"token": "tok-worker-1234", "platform": "ios"})
    w.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    join_push = notifier.sent[-1]
    assert join_push["data"]["type"] == "join_request" and join_push["tokens"] == ["tok-owner-1234"]
    nid = join_push["data"]["notification_id"]
    assert owner.get("/v1/dashboard").json["unread_notifications"] == 1
    # tapping the push: the app marks that record read
    assert owner.post(f"/v1/notifications/{nid}/read").json["read"] is True
    assert owner.get("/v1/dashboard").json["unread_notifications"] == 0

    owner.post("/v1/farm/members/w/approve", json={"role": "worker"})
    welcome = notifier.sent[-1]
    assert welcome["data"]["type"] == "membership_approved" and welcome["tokens"] == ["tok-worker-1234"]
    wid = welcome["data"]["notification_id"]
    assert [n["id"] for n in w.get("/v1/notifications").json if not n["read"]] == [wid]
    # personal: the owner neither sees it nor can mark it
    assert all(n["id"] != wid for n in owner.get("/v1/notifications").json)
    assert owner.post(f"/v1/notifications/{wid}/read").status_code == 404
    assert w.post(f"/v1/notifications/{wid}/read").status_code == 200


def test_join_request_resolved_when_decided_by_anyone(make_client):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    mgr = make_client("mgr"); mgr.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/mgr/approve", json={"role": "manager"})
    for uid, decide in (("a", "approve"), ("b", "reject")):
        make_client(uid).post("/v1/farms/join", json={"invite_code": code_of(owner)})
        unread = [n for n in owner.get("/v1/notifications?unread_only=true").json if n["type"] == "join_request"]
        assert len(unread) == 1
        assert mgr.post(f"/v1/farm/members/{uid}/{decide}").status_code == 200  # the manager decides
        for reader in (owner, mgr):
            assert not [n for n in reader.get("/v1/notifications?unread_only=true").json
                        if n["type"] == "join_request"]
    # a cancelled request is resolved too
    c = make_client("c"); c.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    c.delete("/v1/me/membership")
    assert not [n for n in owner.get("/v1/notifications?unread_only=true").json if n["type"] == "join_request"]


def test_reminder_push_carries_notification_id(client, cow, repo, notifier):
    from datetime import date, timedelta

    from app.services.reminders import run_due_reminders

    client.post("/v1/devices", json={"token": "tok-owner-1234", "platform": "android"})
    client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD",
                                          "date_given": str(date.today() - timedelta(days=10)),
                                          "next_due_date": str(date.today() + timedelta(days=1))})
    notifier.sent.clear()
    run_due_reminders(repo, notifier)
    data = notifier.sent[-1]["data"]
    assert data["notification_id"] and data["animal_id"] == cow["id"] and data["reminder_id"]
    assert client.post(f"/v1/notifications/{data['notification_id']}/read").status_code == 200


def test_worker_cannot_mark_or_delete_manager_only_notification(make_client):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    w = make_client("w"); w.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/w/approve", json={"role": "worker"})
    make_client("z").post("/v1/farms/join", json={"invite_code": code_of(owner)})
    nid = [n for n in owner.get("/v1/notifications").json if n["type"] == "join_request" and not n["read"]][0]["id"]
    assert w.post(f"/v1/notifications/{nid}/read").status_code == 404
    assert w.delete(f"/v1/notifications/{nid}").status_code == 404
    assert owner.post(f"/v1/notifications/{nid}/read").status_code == 200


def test_account_deletion_removes_old_member_records(make_client, repo):
    owner = make_client("own"); owner.post("/v1/farms", json=FARM)
    r = make_client("r"); r.post("/v1/farms/join", json={"invite_code": code_of(owner)})
    owner.post("/v1/farm/members/r/reject")
    assert r.post("/v1/farms", json={"name": "Second Farm", "address": "Route 2, Tunis"}).status_code == 201
    assert me(make_client, "r")["status"] == "active"
    assert make_client("r").delete("/v1/me").status_code == 204
    assert repo.group_list("members", [("uid", "==", "r")]) == []
