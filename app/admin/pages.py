"""More pages of the admin dashboard (same blueprint and sign-in as app/admin/views.py):

- /admin/activity: new accounts, new farms and farms in use week by week; farms that stopped;
- /admin/apps: Android / iPhone split, app versions in use, people on an older version;
- /admin/problems: server errors, emails and pushes that failed (app/ops.py);
- /admin/breeds: which breed has its own photo, the species' photo or none; upload or remove your own photo;
- /admin/broadcast: an announcement to everyone (push + shown once in the apps);
- support actions on /admin/users: resend the verification code, mark an email checked.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import BytesIO

from flask import redirect, request, url_for

from app import ops
from app.admin.views import _form_token, _page, bp, check_form
from app.breed_photos import SPECIES_FILE, photos_dir, slug
from app.breeds import BREEDS
from app.config import get_settings
from app.deps import get_mailer, get_notifier, get_repo
from app.errors import ApiError
from app.routers.support import ANNOUNCEMENTS, announcement_text
from app.services import verification
from app.services.membership import Identity
from app.services.notifier import MEMBERS_CHANNEL
from app.services.reminders import device_tokens


def _back(endpoint: str, message: str, **params):
    return redirect(url_for(endpoint, done=message, **params))


# ------------------------------------------------------------------------ activity
@bp.get("/activity")
def activity():
    """Week by week: new accounts, new farms, farms where something was recorded; and the farms that stopped."""
    repo = get_repo()
    weeks = min(max(int(request.args.get("weeks") or 12), 4), 52)
    data = ops.weekly_activity(repo, ops.ACTIVITY_COLLECTIONS, weeks)
    farms = repo.list("farms")
    stopped = ops.stopped_farms(farms, data["farm_days"])
    top = max([max(w["signups"], w["active_farms"], w["new_farms"]) for w in data["weeks"]] + [1])
    never = [f for f in farms if not data["farm_days"].get(f["id"])]
    return _page("""<h1>Activity</h1><div class="tabs">{% for n in (8, 12, 26, 52) %}<a class="{{ 'on' if n == weeks else '' }}"
href="?weeks={{ n }}">{{ n }} weeks</a>{% endfor %}</div>
<p class="muted">A farm is "in use" in a week when someone recorded or changed something there (animals, health, weights,
milk, money, feed ...).</p><div class="wrap"><table><tr><th>Week of</th><th class="num">New accounts</th><th class="num">New farms</th>
<th class="num">Farms in use</th><th style="width:40%"></th></tr>{% for w in rows|reverse %}<tr><td>{{ w.week }}</td>
<td class="num">{{ w.signups }}</td><td class="num">{{ w.new_farms }}</td><td class="num"><b>{{ w.active_farms }}</b></td>
<td><div class="bar" style="width:{{ (100 * w.active_farms / top)|round }}%"></div>
<div class="bar" style="width:{{ (100 * w.signups / top)|round }}%;background:#D9A441;margin-top:3px"></div></td></tr>{% endfor %}</table></div>
<p class="muted"><span class="pill" style="background:var(--teal);color:#fff">farms in use</span> <span class="pill" style="background:#D9A441">new accounts</span></p>
<h2>Farms that stopped ({{ stopped|length }})</h2><p class="muted">Used on at least 2 days, nothing recorded for 3 weeks or more.
Worth a call: something may be in their way.</p><div class="wrap"><table><tr><th>Farm</th><th>Last used</th><th class="num">Quiet for</th>
<th class="num">Days used</th></tr>{% for s in stopped %}<tr><td><a href="{{ url_for('admin.farm', farm_id=s.farm.id) }}">{{ s.farm.name or s.farm.id }}</a></td>
<td>{{ s.last }}</td><td class="num">{{ s.quiet_for }} days</td><td class="num">{{ s.days_used }}</td></tr>
{% else %}<tr><td colspan="4" class="muted">None.</td></tr>{% endfor %}</table></div>
<h2>Farms created but never used ({{ never|length }})</h2><div class="wrap"><table><tr><th>Farm</th><th>Created</th></tr>
{% for f in never %}<tr><td><a href="{{ url_for('admin.farm', farm_id=f.id) }}">{{ f.name or f.id }}</a></td><td>{{ (f.created_at or '')[:10] }}</td></tr>
{% else %}<tr><td colspan="2" class="muted">None.</td></tr>{% endfor %}</table></div>""",
                 rows=data["weeks"], top=top, stopped=stopped, never=never, weeks=weeks)


# ---------------------------------------------------------------------------- apps
@bp.get("/apps")
def apps():
    """Which phones and app versions people use, and who is on an older version."""
    repo = get_repo()
    users = repo.list("users")
    info = ops.app_versions(users)
    month = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    quiet = sum(1 for u in users if u.get("last_seen") and u["last_seen"] < month)
    phones: dict[str, int] = {}
    for u in users:
        if u.get("device_model"):
            phones[u["device_model"]] = phones.get(u["device_model"], 0) + 1
    return _page("""<h1>Apps</h1><div class="cards">{% for p, n in platforms %}<div class="card"><div class="n">{{ n }}</div>
<div class="l">{{ {'android': 'Android', 'ios': 'iPhone', 'unknown': 'Not known yet (app not opened since this update)'}.get(p, p) }}</div></div>{% endfor %}
<div class="card"><div class="n">{{ quiet }}</div><div class="l">Not seen for 30 days</div></div></div>
<h2>Versions in use</h2><div class="wrap"><table><tr><th>Phone</th><th>Version</th><th class="num">People</th><th></th></tr>
{% for v in versions %}<tr><td>{{ v.platform }}</td><td>{{ v.version }}</td><td class="num">{{ v.users }}</td>
<td>{% if v.newest %}<span class="pill green">newest</span>{% else %}<span class="pill amber">older</span>{% endif %}</td></tr>
{% else %}<tr><td colspan="4" class="muted">No app has reported its version yet.</td></tr>{% endfor %}</table></div>
<h2>On an older version ({{ old|length }})</h2><p class="muted">They do not have the latest fixes: ask them to update from the store.</p>
<div class="wrap"><table><tr><th>Email</th><th>Phone</th><th>Version</th><th>Last seen</th></tr>{% for u in old %}<tr><td>{{ u.email or u.id }}</td>
<td>{{ u.device_model or '' }} <span class="muted">{{ u.os_version or '' }}</span></td><td>{{ u.app_platform }} {{ u.app_version }}</td>
<td>{{ (u.last_seen or '')[:16]|replace('T', ' ') }}</td></tr>{% else %}<tr><td colspan="4" class="muted">Everyone is up to date.</td></tr>{% endfor %}</table></div>
<h2>Phone models</h2><div class="wrap"><table><tr><th>Model</th><th class="num">People</th></tr>{% for m, n in phones %}<tr><td>{{ m }}</td>
<td class="num">{{ n }}</td></tr>{% else %}<tr><td colspan="2" class="muted">None known yet.</td></tr>{% endfor %}</table></div>""",
                 platforms=sorted(info["platforms"].items()), versions=info["versions"], old=info["old"], quiet=quiet,
                 phones=sorted(phones.items(), key=lambda kv: -kv[1])[:30])


# ------------------------------------------------------------------------ problems
@bp.get("/problems")
def problems():
    """Server errors, failed emails and failed pushes of the last days (newest first)."""
    repo = get_repo()
    kind = request.args.get("kind") or None
    days = min(max(int(request.args.get("days") or 30), 1), ops.KEEP_DAYS)
    rows = ops.problems(repo, kind if kind in ops.KINDS else None, days)
    every = ops.problems(repo, None, days)
    counts = {k: sum(1 for p in every if p.get("kind") == k) for k in ops.KINDS}
    return _page("""<h1>Problems</h1><div class="tabs"><a class="{{ '' if kind else 'on' }}" href="?days={{ days }}">All ({{ every|length }})</a>
{% for k, l in [('server_error', 'Server errors'), ('email_failed', 'Emails not sent'), ('push_failed', 'Pushes not sent')] %}
<a class="{{ 'on' if kind == k else '' }}" href="?kind={{ k }}&days={{ days }}">{{ l }} ({{ counts[k] }})</a>{% endfor %}</div>
<p class="muted">Last {{ days }} days. Kept {{ keep }} days. A server error is a bug: the app showed "Something went wrong".
An email not sent means Mailjet refused or could not be reached (check the Mailjet account); pushes: Firebase.</p>
<div class="wrap"><table><tr><th>When (UTC)</th><th>What</th><th>Message</th><th>Details</th></tr>{% for p in rows %}<tr>
<td class="nowrap">{{ (p.at or '')[:16]|replace('T', ' ') }}</td><td><span class="pill {{ 'red' if p.kind == 'server_error' else 'amber' }}">{{ p.kind }}</span></td>
<td>{{ p.message }}</td><td>{% for k in ['method', 'path', 'what', 'email', 'uid', 'title', 'devices'] %}{% if p[k] %}<div><span class="muted">{{ k }}</span> {{ p[k] }}</div>{% endif %}{% endfor %}
{% if p.trace %}<details><summary>Trace</summary><pre>{{ p.trace }}</pre></details>{% endif %}</td></tr>
{% else %}<tr><td colspan="4" class="muted">No problem recorded. 🎉</td></tr>{% endfor %}</table></div>""",
                 rows=rows[:300], every=every, counts=counts, kind=kind, days=days, keep=ops.KEEP_DAYS)


# ------------------------------------------------------------------- breed photos
def _credits_file():
    return photos_dir() / "credits.json"


def _read_credits() -> dict:
    try:
        return json.loads(_credits_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_credits(data: dict) -> None:
    _credits_file().parent.mkdir(parents=True, exist_ok=True)
    _credits_file().write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def breed_rows() -> list[dict]:
    """Every breed: its photo file, whether it has its own photo, the species' photo or none, and the credit."""
    folder = photos_dir()
    credits = _read_credits()
    rows = []
    for species, breeds in BREEDS.items():
        species_photo = (folder / species / f"{SPECIES_FILE}.jpg").is_file()
        entries = [(f"General photo of the species ({species})", SPECIES_FILE)] + [(b[0], slug(b[0])) for b in breeds]
        for name, file in entries:
            own = (folder / species / f"{file}.jpg").is_file()
            key = f"{species}/{file}"
            rows.append({"species": species, "name": name, "file": file, "own": own,
                         "status": "own" if own else ("species" if species_photo and file != SPECIES_FILE else "none"),
                         "credit": (credits.get(key) or {}).get("text") if own else None,
                         "mine": own and key not in credits})
    return rows


def _jpeg(content: bytes, content_type: str) -> bytes:
    """The upload as a JPEG of at most 960 pixels wide (Pillow when installed; a JPEG is kept as it is without)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if not content.startswith(b"\xff\xd8"):
            raise ApiError(415, "Photo must be JPEG, PNG or WebP")
        return content
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - not an image
        raise ApiError(415, "Photo must be JPEG, PNG or WebP") from exc
    image.thumbnail((960, 960))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue()


@bp.get("/breeds")
def breed_photos():
    """Which breeds have their own photo, the species' photo or none; upload your own photo for any of them."""
    rows = breed_rows()
    species = request.args.get("species") or rows[0]["species"]
    counts = {s: {"own": 0, "species": 0, "none": 0} for s in BREEDS}
    for r in rows:
        if r["file"] != SPECIES_FILE:
            counts[r["species"]][r["status"]] += 1
    return _page("""<h1>Breed photos</h1><p class="muted">The photos shown in the apps' breed list. Download the free photos once on the
server with <code>python -m scripts.fetch_breed_photos</code>; replace any of them here with your own (JPEG, PNG or WebP; it is resized).
Your own photo shows no credit line. Photos are kept in <code>{{ folder }}</code>.</p>
<div class="tabs">{% for s, c in counts.items() %}<a class="{{ 'on' if s == species else '' }}" href="?species={{ s }}">{{ s }}
<span class="muted">{{ c.own }}/{{ c.own + c.species + c.none }}</span></a>{% endfor %}</div>
<div class="wrap"><table><tr><th>Photo</th><th>Breed</th><th>Status</th><th>Credit</th><th>Your photo</th></tr>
{% for r in rows if r.species == species %}<tr><td>{% if r.own %}<img class="thumb" src="/v1/breeds/photo/{{ r.species }}/{{ r.file }}.jpg?v={{ stamp }}" alt="">
{% elif r.status == 'species' %}<img class="thumb" style="opacity:.55" src="/v1/breeds/photo/{{ r.species }}/_species.jpg" alt="">{% endif %}</td>
<td><b>{{ r.name }}</b><div class="muted">{{ r.species }}/{{ r.file }}.jpg</div></td>
<td>{% if r.own %}<span class="pill green">own photo</span>{% elif r.status == 'species' %}<span class="pill amber">species' photo</span>
{% else %}<span class="pill red">no photo</span>{% endif %}</td><td class="muted">{{ r.credit or ('your photo' if r.mine else '') }}</td>
<td><form method="post" enctype="multipart/form-data" action="{{ url_for('admin.breed_upload') }}">
<input type="hidden" name="token" value="{{ token }}"><input type="hidden" name="species" value="{{ r.species }}"><input type="hidden" name="file" value="{{ r.file }}">
<input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required> <button class="small">Upload</button></form>
{% if r.own %}<form class="inline" method="post" action="{{ url_for('admin.breed_remove') }}"><input type="hidden" name="token" value="{{ token }}">
<input type="hidden" name="species" value="{{ r.species }}"><input type="hidden" name="file" value="{{ r.file }}">
<button class="small danger" onclick="return confirm('Remove this photo?')">Remove</button></form>{% endif %}</td></tr>{% endfor %}</table></div>""",
                 rows=rows, species=species, counts=counts, token=_form_token("breeds"), folder=str(photos_dir()),
                 stamp=int(datetime.now(timezone.utc).timestamp()))


def _breed_target():
    species = request.form.get("species") or ""
    file = request.form.get("file") or ""
    known = {(r["species"], r["file"]) for r in breed_rows()}
    if (species, file) not in known:
        raise ApiError(404, "Photo not found")
    return species, file


@bp.post("/breeds/upload")
def breed_upload():
    """Save the uploaded photo as the breed's photo (it replaces the downloaded one; no credit line)."""
    check_form("breeds")
    species, file = _breed_target()
    upload = request.files.get("photo")
    limit = get_settings().max_photo_bytes
    content = upload.stream.read(limit + 1) if upload else b""
    if not content:
        return _back("admin.breed_photos", "No photo chosen", species=species)
    if len(content) > limit:
        return _back("admin.breed_photos", f"The photo is larger than {limit // (1024 * 1024)} MB", species=species)
    try:
        jpeg = _jpeg(content, upload.mimetype)  # type: ignore[union-attr]
    except ApiError:
        return _back("admin.breed_photos", "This file is not a JPEG, PNG or WebP photo", species=species)
    target = photos_dir() / species / f"{file}.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(jpeg)
    credits = _read_credits()
    if credits.pop(f"{species}/{file}", None) is not None:
        _write_credits(credits)
    return _back("admin.breed_photos", f"Photo saved for {species}/{file}", species=species)


@bp.post("/breeds/remove")
def breed_remove():
    """Remove a breed's photo (the species' photo is shown instead)."""
    check_form("breeds")
    species, file = _breed_target()
    (photos_dir() / species / f"{file}.jpg").unlink(missing_ok=True)
    credits = _read_credits()
    if credits.pop(f"{species}/{file}", None) is not None:
        _write_credits(credits)
    return _back("admin.breed_photos", f"Photo removed for {species}/{file}", species=species)


# ------------------------------------------------------------------- announcements
def broadcast_devices(repo, target: str) -> list[tuple[str, str, str]]:
    """(uid, token, language) of every phone, or only Android / iPhone users (``target``)."""
    users = repo.list("users")
    if target in ("android", "ios"):
        users = [u for u in users if u.get("app_platform") == target]
    return device_tokens(repo, [u["id"] for u in users])


def send_announcement(repo, notifier, record: dict, target: str) -> int:
    """Push the announcement to the phones, each in its language; forget tokens that no longer work. Returns
    the number of phones it was sent to."""
    devices = broadcast_devices(repo, target)
    by_lang: dict[str, list[str]] = {}
    for _, token, lang in devices:
        by_lang.setdefault(lang, []).append(token)
    invalid: set[str] = set()
    for lang, tokens in by_lang.items():
        title, text = announcement_text(record, lang)
        invalid |= set(notifier.send(tokens, title, text, {"type": "announcement", "announcement_id": record["id"]},
                                     MEMBERS_CHANNEL))
    for uid, token, _ in devices:
        if token in invalid:
            for device in repo.list(f"users/{uid}/devices", [("token", "==", token)]):
                repo.delete(f"users/{uid}/devices", device["id"])
    return len(devices)


@bp.get("/broadcast")
def broadcast():
    """Write an announcement to everyone, and the ones sent before."""
    repo = get_repo()
    sent = sorted(repo.list(ANNOUNCEMENTS), key=lambda a: a.get("created_at") or "", reverse=True)
    phones = {t: len(broadcast_devices(repo, t)) for t in ("all", "android", "ios")}
    return _page("""<h1>Announcements</h1><p class="muted">Sent as a notification to the phones, and shown once in a dialog the next time
each person opens the app (for 30 days), also on phones that missed the notification. Each person reads it in their language: fill
the languages you can; an empty language gets the English text (or the first one filled).</p>
<form class="box" method="post" action="{{ url_for('admin.broadcast_send') }}"><input type="hidden" name="token" value="{{ token }}">
{% for code, lang in [('en', 'English'), ('fr', 'French'), ('ar', 'Arabic')] %}<h2 style="margin-top:6px">{{ lang }}</h2>
<p><label>Title</label><br><input type="text" name="title_{{ code }}" maxlength="80" style="width:100%" {% if code == 'ar' %}dir="rtl"{% endif %}></p>
<p><label>Message</label><br><textarea name="body_{{ code }}" maxlength="600" {% if code == 'ar' %}dir="rtl"{% endif %}></textarea></p>{% endfor %}
<p><label>Send to</label><br><select name="target"><option value="all">Everyone ({{ phones.all }} phones)</option>
<option value="android">Android only ({{ phones.android }} phones)</option><option value="ios">iPhone only ({{ phones.ios }} phones)</option></select></p>
<button onclick="return confirm('Send this announcement now?')">Send</button></form>
<h2>Sent</h2>{% for a in sent %}<div class="box"><div class="muted">{{ (a.created_at or '')[:16]|replace('T', ' ') }} · to {{ a.target }} · {{ a.phones }} phones</div>
{% for code in ['en', 'fr', 'ar'] %}{% if a['body_' ~ code] %}<p {% if code == 'ar' %}dir="rtl"{% endif %}><b>{{ a['title_' ~ code] or 'Farmivo' }}</b><br>{{ a['body_' ~ code] }}</p>{% endif %}{% endfor %}
<form method="post" action="{{ url_for('admin.broadcast_delete', announcement_id=a.id) }}"><input type="hidden" name="token" value="{{ token }}">
<button class="small danger" onclick="return confirm('Stop showing it in the apps?')">Stop showing it</button></form></div>
{% else %}<p class="muted">None yet.</p>{% endfor %}""", sent=sent, phones=phones, token=_form_token("broadcast"))


@bp.post("/broadcast")
def broadcast_send():
    """Save the announcement and push it."""
    check_form("broadcast")
    fields = {}
    for code in ("en", "fr", "ar"):
        fields[f"title_{code}"] = (request.form.get(f"title_{code}") or "").strip()[:80]
        fields[f"body_{code}"] = (request.form.get(f"body_{code}") or "").strip()[:600]
    if not any(fields[f"body_{c}"] for c in ("en", "fr", "ar")):
        return _back("admin.broadcast", "Write the message in at least one language")
    target = request.form.get("target") if request.form.get("target") in ("android", "ios") else "all"
    repo = get_repo()
    record = repo.create(ANNOUNCEMENTS, {**fields, "target": target})
    phones = send_announcement(repo, get_notifier(), record, target)
    repo.update(ANNOUNCEMENTS, record["id"], {"phones": phones})
    return _back("admin.broadcast", f"Sent to {phones} phones")


@bp.post("/broadcast/<announcement_id>/delete")
def broadcast_delete(announcement_id: str):
    """Stop showing an announcement in the apps (a push already sent stays on the phones)."""
    check_form("broadcast")
    get_repo().delete(ANNOUNCEMENTS, announcement_id)
    return _back("admin.broadcast", "It is no longer shown in the apps")


# ------------------------------------------------------------------------- support
@bp.post("/users/<uid>/resend-code")
def resend_code(uid: str):
    """Send the user a new verification code (the usual limits apply: 60 s between codes, 5 an hour)."""
    check_form("support")
    repo = get_repo()
    user = repo.get("users", uid) or {}
    email = user.get("email") or next((m.get("email") for m in repo.group_list("members") if m["id"] == uid
                                        and m.get("email")), None)
    if not email:
        return _back("admin.users", "This account has no email address known here")
    try:
        verification.send_code(repo, get_mailer(), Identity(uid=uid, email=email), get_settings().code_hash_secret)
    except ApiError as exc:
        return _back("admin.users", f"Not sent: {exc.detail}", q=email)
    return _back("admin.users", f"A new code was sent to {email}", q=email)


@bp.post("/users/<uid>/mark-verified")
def mark_verified(uid: str):
    """Count the user's email as checked (when the code email does not arrive and you know the person)."""
    check_form("support")
    verification.mark_verified(get_repo(), uid)
    return _back("admin.users", "Email marked as checked: the person can now create or join a farm")
