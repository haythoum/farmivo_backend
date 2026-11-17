"""Talking with the people who use the apps: feedback sent from the app (/v1/feedback) and the announcements the
admin broadcasts (/v1/announcements). Both need a signed-in account but no farm.

Feedback: the app's "Send feedback" screen sends a text, the screen it was opened from and, if the user wants,
a screenshot (multipart field ``screenshot``). It lands in the admin dashboard's inbox (/admin/feedback) with the
app version and phone (headers X-Farmivo-*, see app/ops.py) and the farm. At most 10 per hour per account.

Announcements: written in the admin dashboard (/admin/broadcast) in English, French and/or Arabic; sent as a push
to every phone and listed here for 30 days so the apps show each one once (in a dialog) even when the push was
missed. Each user reads it in their language (English when that language was left empty).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from app import ops
from app.config import get_settings
from app.deps import get_identity, get_photo_store, get_repo
from app.errors import ApiError
from app.i18n import normalize, request_lang
from app.services import membership as membership_service
from app.services.photos import ALLOWED_TYPES
from app.web import out

bp = Blueprint("support", __name__)

FEEDBACK = "feedback"
ANNOUNCEMENTS = "announcements"
MAX_FEEDBACK_PER_HOUR = 10
MAX_TEXT = 3000
SHOW_DAYS = 30


def _form() -> dict:
    """The fields of a JSON body or a multipart form."""
    if request.is_json:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    return request.form.to_dict()


@bp.post("/feedback")
def send_feedback():
    """POST /v1/feedback {text, screen?} (JSON, or multipart with an optional ``screenshot`` image) -> 201 {"id"}."""
    identity = get_identity()
    repo = get_repo()
    data = _form()
    text = str(data.get("text") or "").strip()
    if not text:
        raise ApiError(422, [{"loc": ["body", "text"], "msg": "Field required", "type": "missing"}])
    if len(text) > MAX_TEXT:
        raise ApiError(422, [{"loc": ["body", "text"], "msg": f"String should have at most {MAX_TEXT} characters",
                              "type": "string_too_long"}])
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    recent = [f for f in repo.list(FEEDBACK, [("uid", "==", identity.uid)]) if (f.get("created_at") or "") >= since]
    if len(recent) >= MAX_FEEDBACK_PER_HOUR:
        raise ApiError(429, "Too many messages. Try again in an hour")

    shot = request.files.get("screenshot")
    content = b""
    if shot is not None:
        if shot.mimetype not in ALLOWED_TYPES:
            raise ApiError(415, "Photo must be JPEG, PNG or WebP")
        limit = get_settings().max_photo_bytes
        content = shot.stream.read(limit + 1)
        if len(content) > limit:
            raise ApiError(413, f"Photo exceeds {limit // (1024 * 1024)} MB")

    state = membership_service.resolve(repo, identity)
    farm = state.farm or {}
    user = repo.get("users", identity.uid) or {}
    record = repo.create(FEEDBACK, {
        "uid": identity.uid, "email": identity.email, "name": user.get("name") or identity.name,
        "farm_id": farm.get("id"), "farm_name": farm.get("name"), "role": state.role,
        "text": text, "screen": str(data.get("screen") or "")[:80] or None,
        "lang": request_lang(), "status": "new", **ops.client_info(request.headers),
    })
    if content:
        url = get_photo_store().save("_feedback", record["id"], content, shot.mimetype)  # type: ignore[union-attr]
        repo.update(FEEDBACK, record["id"], {"screenshot_url": url})
    return out({"id": record["id"]}, 201)


def announcement_text(record: dict, lang: str) -> tuple[str, str]:
    """(title, body) of an announcement in ``lang`` (English, then any filled language, when it is empty)."""
    order = [lang, "en", "fr", "ar"]
    for code in order:
        if (record.get(f"body_{code}") or "").strip():
            return (record.get(f"title_{code}") or "Farmivo").strip(), record[f"body_{code}"].strip()
    return "Farmivo", ""


@bp.get("/announcements")
def list_announcements():
    """GET /v1/announcements - the admin's announcements of the last 30 days, newest first:
    [{"id", "title", "body", "sent_at"}] in the user's language. The apps show each id once."""
    identity = get_identity()
    repo = get_repo()
    user = repo.get("users", identity.uid) or {}
    lang = normalize(user.get("lang")) or request_lang()
    since = (datetime.now(timezone.utc) - timedelta(days=SHOW_DAYS)).isoformat(timespec="seconds")
    rows = sorted((a for a in repo.list(ANNOUNCEMENTS) if (a.get("created_at") or "") >= since),
                  key=lambda a: a.get("created_at") or "", reverse=True)
    result = []
    for a in rows:
        title, text = announcement_text(a, lang)
        if text:
            result.append({"id": a["id"], "title": title, "body": text, "sent_at": a.get("created_at")})
    return out(result)
