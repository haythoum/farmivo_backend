"""Languages (Accept-Language: ar, fr, en): error texts, pushes in the recipient's language, stored notifications,
reminder titles, the verification email, and the push payload sent to Firebase."""
from datetime import date, timedelta

from app.i18n import MESSAGES, negotiate, render, t, translate_detail

FARM = {"name": "Green Valley Farm", "address": "Route de Mateur, Bizerte"}
FR = {"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
AR = {"Accept-Language": "ar-TN"}


def iso(days=0):
    return (date.today() + timedelta(days=days)).isoformat()


# ------------------------------------------------------------------ catalog and negotiation

def test_every_message_has_three_languages_and_same_placeholders():
    import re

    for key, entry in MESSAGES.items():
        assert set(entry) == {"en", "fr", "ar"}, key
        names = {lang: set(re.findall(r"\{(\w+)\}", text)) for lang, text in entry.items()}
        assert names["fr"] == names["en"] == names["ar"], key


def test_negotiate():
    assert negotiate(None) == "en"
    assert negotiate("") == "en"
    assert negotiate("de-DE,de;q=0.9") == "en"
    assert negotiate("fr-FR,fr;q=0.9,en;q=0.8") == "fr"
    assert negotiate("ar") == "ar"
    assert negotiate("de, ar;q=0.5, fr;q=0.7") == "fr"
    assert negotiate("en;q=0.2, ar;q=0.9") == "ar"


def test_t_and_render_fallbacks():
    assert t("push.approved.title", "fr", farm="GVF") == "Bienvenue à GVF"
    assert t("push.approved.title", "xx", farm="GVF") == "Welcome to GVF"  # unknown language -> English
    assert t("no.such.key", "fr") == "no.such.key"
    nested = render("push.reminder.body", "ar", {"title": {"$t": "reminder.birth", "params": {}},
                                                 "when": {"$t": "when.tomorrow", "params": {}}})
    assert nested == "ولادة متوقعة - غدًا"


def test_translate_detail_patterns():
    assert translate_detail("Wrong code. 3 attempts left", "fr") == "Code incorrect. Il reste 3 essais"
    assert translate_detail("Wrong code. 1 attempt left", "ar") == "رمز غير صحيح. تبقّت محاولة واحدة"
    assert translate_detail("Ear tag 'C1' is already used on this farm", "fr").startswith("La boucle 'C1'")
    assert translate_detail("Something we never wrote", "fr") == "Something we never wrote"
    items = translate_detail([{"loc": ["body", "name"], "msg": "Field required", "type": "missing"}], "ar")
    assert items[0]["msg"] == "حقل مطلوب" and items[0]["type"] == "missing"


# ------------------------------------------------------------------ errors through the API

def test_error_details_follow_accept_language(make_client):
    c = make_client("nobody")
    en = c.get("/v1/animals")
    fr = c.get("/v1/animals", headers=FR)
    ar = c.get("/v1/animals", headers=AR)
    assert en.json == {"detail": "You are not a member of a farm yet", "code": "no_farm"}
    assert fr.json == {"detail": "Vous n'êtes encore membre d'aucune ferme", "code": "no_farm"}
    assert ar.json["detail"] == "لست عضوًا في أي مزرعة بعد" and ar.json["code"] == "no_farm"
    assert c.post("/v1/farms/join", json={"invite_code": "ZZZ-2222"}, headers=FR).json["detail"] == \
        "Aucune ferme avec ce code"
    assert c.get("/v1/nope", headers=AR).json["detail"] == "غير موجود"


def test_validation_messages_translated(make_client):
    c = make_client("u1")
    r = c.post("/v1/farms", json={"address": "Somewhere 12"}, headers=FR)
    assert r.status_code == 422
    assert any(item["msg"] == "Champ obligatoire" for item in r.json["detail"])


def test_wrong_code_translated(make_client, mailer):
    c = make_client("new", verified=False)
    c.post("/v1/me/verification/send")
    wrong = "000000" if mailer.last_code != "000000" else "111111"
    r = c.post("/v1/me/verification/verify", json={"code": wrong}, headers=AR)
    assert r.status_code == 400 and r.json["code"] == "wrong_code" and r.json["detail"].startswith("رمز غير صحيح")


# ------------------------------------------------------------------ languages stored per user and device

def test_device_language_and_user_language_are_stored(make_client, repo):
    c = make_client("u1")
    c.post("/v1/devices", json={"token": "token-explicit-1", "platform": "android", "language": "ar"})
    c.post("/v1/devices", json={"token": "token-header-12", "platform": "ios"}, headers=FR)
    c.post("/v1/devices", json={"token": "token-nolang-123", "platform": "ios"})
    devices = {d["token"]: d.get("language") for d in repo.list("users/u1/devices")}
    assert devices == {"token-explicit-1": "ar", "token-header-12": "fr", "token-nolang-123": None}
    assert repo.get("users", "u1")["lang"] == "fr"
    assert c.post("/v1/devices", json={"token": "token-bad-12345", "platform": "ios", "language": "de"}).status_code == 422


def test_language_kept_when_user_record_changes(make_client, repo):
    c = make_client("u1")
    c.get("/v1/me", headers=AR)
    assert c.post("/v1/farms", json=FARM).status_code == 201
    user = repo.get("users", "u1")
    assert user["lang"] == "ar" and user["farm_id"]


# ------------------------------------------------------------------ pushes in the recipient's language

def test_join_push_in_each_managers_language(make_client, notifier):
    owner = make_client("owner")
    owner.post("/v1/farms", json=FARM)
    owner.post("/v1/devices", json={"token": "owner-token-ar", "platform": "android", "language": "ar"})
    code = owner.get("/v1/farm").json["invite_code"]
    manager = make_client("mgr")
    manager.post("/v1/farms/join", json={"invite_code": code})
    owner.post("/v1/farm/members/mgr/approve", json={"role": "manager"})
    manager.post("/v1/devices", json={"token": "manager-token-fr", "platform": "ios", "language": "fr"})
    notifier.sent.clear()
    # the joiner writes in English: each recipient still gets their own language
    make_client("ali", name="Ali").post("/v1/farms/join", json={"invite_code": code})
    by_token = {s["tokens"][0]: s for s in notifier.sent}
    assert set(by_token) == {"owner-token-ar", "manager-token-fr"}
    assert by_token["owner-token-ar"]["title"] == "Ali يريد الانضمام"
    assert by_token["manager-token-fr"]["title"] == "Ali souhaite rejoindre la ferme"
    for sent in notifier.sent:
        assert sent["channel"] == "farmivo_members"
        assert sent["data"]["type"] == "join_request" and sent["data"]["farm_id"]


def test_approval_push_uses_requesters_language(make_client, notifier):
    owner = make_client("owner")
    owner.post("/v1/farms", json=FARM)
    code = owner.get("/v1/farm").json["invite_code"]
    ali = make_client("ali")
    ali.post("/v1/devices", json={"token": "ali-token-123", "platform": "android"}, headers=AR)
    ali.post("/v1/farms/join", json={"invite_code": code})
    notifier.sent.clear()
    owner.post("/v1/farm/members/ali/approve", headers=FR)  # the owner's language doesn't matter
    sent = notifier.sent[-1]
    assert sent["tokens"] == ["ali-token-123"] and sent["title"] == "مرحبًا بك في Green Valley Farm"
    assert sent["data"]["type"] == "membership_approved"
    assert sent["data"]["farm_id"] == owner.get("/v1/farm").json["id"] and sent["data"]["notification_id"]


def test_stored_notifications_render_in_readers_language(client, make_client):
    code = client.get("/v1/farm").json["invite_code"]
    make_client("ali", name="Ali").post("/v1/farms/join", json={"invite_code": code})
    en = client.get("/v1/notifications").json[0]
    fr = client.get("/v1/notifications", headers=FR).json[0]
    assert en["title"] == "Ali wants to join" and fr["title"] == "Ali souhaite rejoindre la ferme"
    assert "Membres" in fr["body"]


# ------------------------------------------------------------------ reminders

def test_reminder_titles_and_reminder_push_translated(client, cow, repo, notifier):
    client.post("/v1/devices", json={"token": "phone-fr-12345", "platform": "android", "language": "fr"})
    client.post("/v1/vaccinations", json={"animal_id": cow["id"], "vaccine_name": "FMD", "date_given": iso(-10),
                                          "next_due_date": iso(1)})
    assert client.get("/v1/reminders").json[0]["title"] == "Vaccination due: FMD (Bella (C1))"
    assert client.get("/v1/reminders", headers=FR).json[0]["title"] == "Vaccin à faire : FMD (Bella (C1))"
    assert client.get("/v1/dashboard", headers=AR).json["health"]["upcoming_vaccinations"][0]["title"] == \
        "موعد التطعيم: FMD (Bella (C1))"
    from app.services.reminders import run_due_reminders

    run_due_reminders(repo, notifier)
    push = notifier.sent[-1]
    assert push["title"] == "Rappel Farmivo" and push["body"] == "Vaccin à faire : FMD (Bella (C1)) - demain"
    assert push["channel"] == "farmivo_reminders" and push["data"]["type"] == "vaccination"
    # the animal is named once (it used to appear twice: "Bella (C1): Vaccination due: FMD (Bella (C1)) is ...")
    assert push["body"].count("Bella") == 1


def test_custom_reminder_keeps_its_text(client):
    client.post("/v1/reminders", json={"title": "Buy feed", "due_date": iso(3)})
    assert client.get("/v1/reminders", headers=AR).json[0]["title"] == "Buy feed"


# ------------------------------------------------------------------ email

def test_verification_email_language(make_client, mailer):
    c = make_client("new", verified=False)
    c.post("/v1/me/verification/send", headers=AR)
    assert mailer.langs[-1] == "ar"


def test_email_content_in_arabic_is_rtl():
    from app.services.mailer import code_message

    msg = code_message("contact@quadralens.tn", "Farmivo", "a@b.c", "482715", 15, "ar")["Messages"][0]
    assert msg["Subject"] == "رمز التحقق الخاص بك في Farmivo"
    assert 'dir="rtl"' in msg["HTMLPart"] and "4 8 2 7 1 5" in msg["HTMLPart"]
    assert "482715" in msg["TextPart"] and "15" in msg["TextPart"]
    fr = code_message("contact@quadralens.tn", "Farmivo", "a@b.c", "482715", 15, "fr")["Messages"][0]
    assert fr["Subject"] == "Votre code de vérification Farmivo" and 'dir="ltr"' in fr["HTMLPart"]


# ------------------------------------------------------------------ Firebase payload

def test_fcm_payload_shape(monkeypatch):
    import sys
    import types

    calls = {}
    messaging = types.SimpleNamespace()
    for name in ("Notification", "AndroidNotification", "AndroidConfig", "Aps", "APNSPayload", "APNSConfig",
                 "MulticastMessage"):
        setattr(messaging, name, (lambda n: (lambda **kw: calls.setdefault(n, kw) or kw))(name))
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin.messaging = messaging
    monkeypatch.setitem(sys.modules, "firebase_admin", firebase_admin)
    monkeypatch.setitem(sys.modules, "firebase_admin.messaging", messaging)
    from app.services.notifier import fcm_message

    fcm_message(["t1"], "Title", "Body", {"type": "join_request", "farm_id": "f1", "skip": None}, "farmivo_members")
    assert calls["Notification"] == {"title": "Title", "body": "Body"}
    assert calls["AndroidNotification"] == {"channel_id": "farmivo_members", "icon": "ic_notification",
                                            "color": "#1F6F6B"}
    assert calls["AndroidConfig"]["priority"] == "high"
    assert calls["Aps"] == {"sound": "default", "mutable_content": True}
    assert calls["MulticastMessage"]["data"] == {"type": "join_request", "farm_id": "f1"}


def test_join_requests_hidden_from_workers(client, make_client):
    code = client.get("/v1/farm").json["invite_code"]
    worker = make_client("w1")
    worker.post("/v1/farms/join", json={"invite_code": code})
    client.post("/v1/farm/members/w1/approve", json={"role": "worker"})
    make_client("ali", name="Ali").post("/v1/farms/join", json={"invite_code": code})
    assert any(n["type"] == "join_request" for n in client.get("/v1/notifications").json)
    seen = worker.get("/v1/notifications").json
    assert not any(n["type"] == "join_request" for n in seen)
    # the only unread item the worker counts is their own "welcome" (membership_approved)
    assert [n["type"] for n in seen if not n["read"]] == ["membership_approved"]
    assert worker.get("/v1/dashboard").json["unread_notifications"] == 1
