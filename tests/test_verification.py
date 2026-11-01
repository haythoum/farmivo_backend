"""Email verification with a 6-digit code (POST /v1/me/verification/send and /verify)."""
from datetime import timedelta

import pytest

from app.services import verification


@pytest.fixture
def clock(monkeypatch):
    """Lets a test move time forward: clock.advance(seconds=...)."""
    class Clock:
        def __init__(self):
            self.now = verification.now()

        def advance(self, **kw):
            self.now += timedelta(**kw)

    c = Clock()
    monkeypatch.setattr(verification, "now", lambda: c.now)
    return c


@pytest.fixture
def newbie(make_client):
    """A freshly created account whose email is not verified yet."""
    return make_client("newbie", email="newbie@example.com", verified=False)


def test_me_reports_unverified_and_farm_actions_blocked(newbie):
    assert newbie.get("/v1/me").json["email_verified"] is False
    r = newbie.post("/v1/farms", json={"name": "New Farm", "address": "Somewhere 12"})
    assert r.status_code == 403 and r.json == {"detail": "Verify your email first", "code": "email_unverified"}
    r = newbie.post("/v1/farms/join", json={"invite_code": "GVF-7K3P"})
    assert r.status_code == 403 and r.json["code"] == "email_unverified"


def test_send_and_verify_happy_path(newbie, mailer, clock):
    r = newbie.post("/v1/me/verification/send")
    assert r.status_code == 200
    assert r.json == {"sent_to": "newbie@example.com", "resend_after_seconds": 60, "expires_in_seconds": 900}
    to, code = mailer.sent[-1]
    assert to == "newbie@example.com" and len(code) == 6 and code.isdigit()
    r = newbie.post("/v1/me/verification/verify", json={"code": f" {code[:3]} {code[3:]} "})
    assert r.status_code == 200 and r.json["email_verified"] is True and r.json["status"] == "none"
    assert newbie.get("/v1/me").json["email_verified"] is True
    assert newbie.post("/v1/farms", json={"name": "New Farm", "address": "Somewhere 12"}).status_code == 201


def test_code_is_stored_hashed_only(newbie, mailer, repo, clock):
    newbie.post("/v1/me/verification/send")
    record = repo.get("email_codes", "newbie")
    assert mailer.last_code not in str(record)
    assert record["code_hash"] and record["attempts"] == 0 and record["expires_at"] and record["last_sent_at"]


def test_cooldown_then_resend(newbie, mailer, clock):
    assert newbie.post("/v1/me/verification/send").status_code == 200
    clock.advance(seconds=20)
    r = newbie.post("/v1/me/verification/send")
    assert r.status_code == 429 and r.json["code"] == "too_soon" and 39 <= r.json["retry_after"] <= 41
    assert "Please wait" in r.json["detail"]
    clock.advance(seconds=41)
    assert newbie.post("/v1/me/verification/send").status_code == 200
    assert len(mailer.sent) == 2


def test_new_code_replaces_old_one(newbie, mailer, clock):
    newbie.post("/v1/me/verification/send")
    old = mailer.last_code
    clock.advance(seconds=61)
    newbie.post("/v1/me/verification/send")
    new = mailer.last_code
    if old != new:
        assert newbie.post("/v1/me/verification/verify", json={"code": old}).json["code"] == "wrong_code"
    assert newbie.post("/v1/me/verification/verify", json={"code": new}).status_code == 200


def test_hourly_limit(newbie, clock):
    for _ in range(5):
        assert newbie.post("/v1/me/verification/send").status_code == 200
        clock.advance(seconds=61)
    r = newbie.post("/v1/me/verification/send")
    assert r.status_code == 429 and r.json["code"] == "too_many_codes"
    clock.advance(hours=1)
    assert newbie.post("/v1/me/verification/send").status_code == 200


def test_wrong_code_attempts_then_burnt(newbie, mailer, clock):
    newbie.post("/v1/me/verification/send")
    wrong = "000000" if mailer.last_code != "000000" else "111111"
    for left in (4, 3, 2, 1):
        r = newbie.post("/v1/me/verification/verify", json={"code": wrong})
        assert r.status_code == 400 and r.json["code"] == "wrong_code"
        assert r.json["detail"] == f"Wrong code. {left} attempt{'s' if left != 1 else ''} left"
    r = newbie.post("/v1/me/verification/verify", json={"code": wrong})
    assert r.status_code == 429 and r.json["code"] == "too_many_attempts"
    # the right code no longer works: ask for a new one
    r = newbie.post("/v1/me/verification/verify", json={"code": mailer.last_code})
    assert r.status_code == 410 and r.json["code"] == "code_expired"


def test_expired_code(newbie, mailer, clock):
    newbie.post("/v1/me/verification/send")
    clock.advance(minutes=15, seconds=1)
    r = newbie.post("/v1/me/verification/verify", json={"code": mailer.last_code})
    assert r.status_code == 410 and r.json == {"detail": "The code has expired. Ask for a new one",
                                               "code": "code_expired"}


def test_verify_without_any_code(newbie):
    r = newbie.post("/v1/me/verification/verify", json={"code": "123456"})
    assert r.status_code == 410 and r.json["code"] == "code_expired"


def test_already_verified(make_client, mailer):
    c = make_client("claimed", verified=True)  # Firebase token already says email_verified
    assert c.get("/v1/me").json["email_verified"] is True
    r = c.post("/v1/me/verification/send")
    assert r.status_code == 409 and r.json == {"detail": "Your email is already verified", "code": "already_verified"}
    assert mailer.sent == []


def test_token_claim_is_saved(make_client, repo):
    make_client("claimed", verified=True).get("/v1/me")
    assert repo.get("users", "claimed")["email_verified"] is True


def test_active_members_are_grandfathered(make_client, repo):
    owner = make_client("legacy", verified=True)
    owner.post("/v1/farms", json={"name": "Old Farm", "address": "Road 1, Town"})
    repo.update("users", "legacy", {"email_verified": False})
    again = make_client("legacy", verified=False)  # token without the claim
    assert again.get("/v1/me").json["email_verified"] is True
    assert repo.get("users", "legacy")["email_verified"] is True
    assert again.get("/v1/animals").status_code == 200


def test_verified_flag_survives_leaving_a_farm(make_client, repo, mailer, clock):
    owner = make_client("boss")
    owner.post("/v1/farms", json={"name": "Green Valley Farm", "address": "Route de Mateur"})
    code = owner.get("/v1/farm").json["invite_code"]
    worker = make_client("w1", verified=False)
    worker.post("/v1/me/verification/send")
    worker.post("/v1/me/verification/verify", json={"code": mailer.last_code})
    assert worker.post("/v1/farms/join", json={"invite_code": code}).status_code == 200
    assert worker.delete("/v1/me/membership").json["status"] == "none"
    assert repo.get("users", "w1")["email_verified"] is True
    assert worker.get("/v1/me").json["email_verified"] is True


def test_no_email_in_token(make_client):
    c = make_client("phone-user", verified=False)
    c.application.config["FARMIVO_OVERRIDES"]["email"] = None
    r = c.post("/v1/me/verification/send")
    assert r.status_code == 400 and r.json["code"] == "no_email"


def test_email_failure_is_502(newbie, mailer):
    mailer.fail = True
    r = newbie.post("/v1/me/verification/send")
    assert r.status_code == 502 and r.json == {"detail": "We could not send the email. Try again later",
                                               "code": "email_failed"}
    mailer.fail = False
    assert newbie.post("/v1/me/verification/send").status_code == 200  # a failed send starts no cooldown


def test_email_message_content():
    from app.services.mailer import code_message

    msg = code_message("contact@quadralens.tn", "Farmivo", "a@b.c", "482715", 15)["Messages"][0]
    assert msg["Subject"] == "Your Farmivo verification code"
    text, html = msg["TextPart"], msg["HTMLPart"]
    assert "482715" in text and "15 minutes" in text and "ignore this email" in text
    assert "4 8 2 7 1 5" in html and "#1F6F6B" in html and "Powered by Quadralens" in html


def test_mailjet_payload_and_success(monkeypatch):
    """MailjetMailer sends the v3.1 payload and accepts only a 'success' answer."""
    from app.services import mailer as m

    sent = {}

    class Result:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, answer):
            self.answer = answer
            self.send = self

        def create(self, data, timeout=None):
            sent["data"] = data
            return self.answer

    mj = m.MailjetMailer("key", "secret", "contact@quadralens.tn", "Farmivo")
    monkeypatch.setattr(mj, "_client", lambda version="v3.1": FakeClient(Result(200, {"Messages": [{"Status": "success"}]})))
    mj.send_code("new@farm.tn", "123456", 15)
    msg = sent["data"]["Messages"][0]
    assert msg["From"] == {"Email": "contact@quadralens.tn", "Name": "Farmivo"}
    assert msg["To"] == [{"Email": "new@farm.tn"}]
    assert "123456" in msg["TextPart"] and "1 2 3 4 5 6" in msg["HTMLPart"] and "15 minutes" in msg["HTMLPart"]

    monkeypatch.setattr(mj, "_client", lambda version="v3.1": FakeClient(Result(401, {"ErrorMessage": "bad key"})))
    import pytest

    with pytest.raises(m.MailError):
        mj.send_code("new@farm.tn", "123456", 15)
