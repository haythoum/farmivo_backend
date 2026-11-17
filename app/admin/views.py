"""Pages of the admin dashboard (see app/admin/__init__.py): overview, farms, users and deleting a farm here;
activity, app versions, problems, breed photos, announcements and the support actions in
app/admin/pages.py. Every form that changes something carries a token tied to the admin password (_token)."""
from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, abort, redirect, render_template_string, request, url_for

from app.config import get_settings
from app.deps import get_photo_store, get_repo
from app.repository import farm_path
from app.schemas import ON_FARM_STATUSES
from app.services.account import FARM_COLLECTIONS, delete_farm
from app.services.membership import members_path

bp = Blueprint("admin", __name__)

LOCAL = {"127.0.0.1", "::1", "localhost"}
# Opened to the network (FARMIVO_ADMIN_ALLOW_REMOTE): wrong passwords from one address are counted, and after
# MAX_FAILS within LOCK_MINUTES that address is refused for LOCK_MINUTES even with the right password.
MAX_FAILS = 8
LOCK_MINUTES = 15
MIN_REMOTE_PASSWORD = 12
_fails: dict[str, list[datetime]] = {}


def _recent_fails(address: str, now: datetime) -> list[datetime]:
    kept = [t for t in _fails.get(address, []) if now - t < timedelta(minutes=LOCK_MINUTES)]
    _fails[address] = kept
    return kept


@bp.before_request
def _guard():
    """Off without a password; local requests only (unless allowed); HTTP Basic user admin + password.
    Opened to the network: a password of at least 12 characters, and an address with 8 wrong passwords in
    15 minutes is refused for 15 minutes."""
    settings = get_settings()
    if not settings.admin_password:
        abort(404)
    if not settings.admin_allow_remote:
        forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
        if request.remote_addr not in LOCAL or forwarded:
            abort(404)
    elif len(settings.admin_password) < MIN_REMOTE_PASSWORD:
        return Response(f"Farmivo admin: open to the network only with a password of at least {MIN_REMOTE_PASSWORD} "
                        "characters (FARMIVO_ADMIN_PASSWORD in .env).", 403, {"Content-Type": "text/plain; charset=utf-8"})
    address = request.remote_addr or "?"
    now = datetime.now(timezone.utc)
    if len(_recent_fails(address, now)) >= MAX_FAILS:
        return Response(f"Farmivo admin: too many wrong passwords from this address. Try again in {LOCK_MINUTES} minutes.",
                        429, {"Content-Type": "text/plain; charset=utf-8", "Retry-After": str(LOCK_MINUTES * 60)})
    auth = request.authorization
    ok = (auth is not None and auth.type == "basic" and hmac.compare_digest(auth.username or "", "admin")
          and hmac.compare_digest((auth.password or "").encode(), settings.admin_password.encode()))
    if not ok:
        if auth is not None:  # the browser's first request carries no password: not a wrong one
            _fails.setdefault(address, []).append(now)
        return Response("Farmivo admin: sign in", 401, {"WWW-Authenticate": 'Basic realm="Farmivo admin"'})
    _fails.pop(address, None)
    return None


@bp.after_request
def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _token(farm_id: str) -> str:
    """Form token for deleting one farm (ties the form to this farm and to the admin password)."""
    key = (get_settings().admin_password or "").encode()
    return hmac.new(key, f"delete:{farm_id}".encode(), hashlib.sha256).hexdigest()


def _form_token(action: str) -> str:
    """Token of the dashboard's forms for ``action`` (support, breeds, broadcast): a page of another
    site cannot post them (it does not know the admin password the token is made from)."""
    key = (get_settings().admin_password or "").encode()
    return hmac.new(key, f"form:{action}".encode(), hashlib.sha256).hexdigest()


def check_form(action: str) -> None:
    """400 unless the posted form carries the token of ``action``."""
    if not hmac.compare_digest(request.form.get("token", ""), _form_token(action)):
        abort(400)


def _owner(members: list[dict]) -> dict:
    return next((m for m in members if m.get("role") == "owner" and m.get("status") == "active"), {})


def _farm_row(repo, farm: dict) -> dict:
    members = repo.list(members_path(farm["id"]))
    animals = repo.list(farm_path(farm["id"], "animals"))
    stamps = [farm.get("updated_at") or ""] + [a.get("updated_at") or "" for a in animals]
    stamps += [t.get("updated_at") or "" for t in repo.list(farm_path(farm["id"], "transactions"))]
    owner = _owner(members)
    return {
        "id": farm["id"], "name": farm.get("name") or "(no name)", "address": farm.get("address") or "",
        "currency": farm.get("currency") or "", "created": (farm.get("created_at") or "")[:10],
        "last_activity": max(stamps)[:10] if any(stamps) else "",
        "owner": owner.get("email") or owner.get("name") or "?",
        "members": sum(1 for m in members if m.get("status") == "active"),
        "pending": sum(1 for m in members if m.get("status") == "pending"),
        "animals": sum(1 for a in animals if a.get("status") in ON_FARM_STATUSES),
        "animals_all": len(animals),
        "barns": len(repo.list(farm_path(farm["id"], "barns"))),
    }


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Farmivo admin</title><style>
:root{--teal:#1F6F6B;--ink:#1E2A29;--muted:#5B6B69;--line:#E1E8E6;--bg:#FBF6EE;--red:#B3261E}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--teal);color:#fff;padding:14px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header b{font-size:18px}header a{color:#fff;text-decoration:none;opacity:.9}header a:hover{opacity:1;text-decoration:underline}
main{padding:20px;max-width:1200px;margin:0 auto}h1{font-size:22px;margin:4px 0 16px}h2{font-size:17px;margin:24px 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}.card .n{font-size:26px;font-weight:800;color:var(--teal)}
.card .l{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#F2F5F4;font-size:13px;color:var(--muted)}
td.num,th.num{text-align:right}tr:last-child td{border-bottom:0}a{color:var(--teal)}
form.search{display:flex;gap:8px;margin-bottom:12px}input[type=text],input[type=search]{padding:9px 10px;border:1px solid var(--line);border-radius:10px;font:inherit;min-width:260px}
button{padding:9px 14px;border-radius:10px;border:0;background:var(--teal);color:#fff;font:inherit;font-weight:700;cursor:pointer}
button.danger{background:var(--red)}.box{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:12px}
.danger-box{border-color:#F3C1BC;background:#FFF6F5}.muted{color:var(--muted)}.ok{background:#E7F4E3;border:1px solid #BFE0B8;padding:10px 12px;border-radius:10px}
.wrap{overflow-x:auto}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.tabs a{padding:6px 12px;border-radius:999px;background:#fff;border:1px solid var(--line);text-decoration:none}
.tabs a.on{background:var(--teal);color:#fff;border-color:var(--teal)}.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#F2F5F4}
.pill.red{background:#FDECEA;color:var(--red)}.pill.green{background:#E7F4E3;color:#2E7D32}.pill.amber{background:#FFF4DC;color:#8A5A00}
.bar{height:10px;background:var(--teal);border-radius:6px;min-width:2px}.inline{display:inline}button.small{padding:5px 10px;font-size:13px}
textarea{width:100%;min-height:90px;padding:9px 10px;border:1px solid var(--line);border-radius:10px;font:inherit}
pre{white-space:pre-wrap;font-size:12px;background:#F7F9F8;padding:8px;border-radius:8px;max-height:260px;overflow:auto}
img.thumb{width:72px;height:54px;object-fit:cover;border-radius:8px;background:#F2F5F4}label{font-weight:600}
</style></head><body><header><b>Farmivo admin</b><a href="{{ url_for('admin.overview') }}">Overview</a>
<a href="{{ url_for('admin.activity') }}">Activity</a><a href="{{ url_for('admin.apps') }}">Apps</a>
<a href="{{ url_for('admin.problems') }}">Problems</a>
<a href="{{ url_for('admin.farms') }}">Farms</a><a href="{{ url_for('admin.users') }}">Users</a>
<a href="{{ url_for('admin.breed_photos') }}">Breed photos</a><a href="{{ url_for('admin.broadcast') }}">Announcements</a>
</header><main>{% if flash %}<p class="ok">{{ flash }}</p>{% endif %}{{ body|safe }}</main></body></html>"""


def _page(body_template: str, **ctx) -> str:
    """A dashboard page: the menu, an optional ``?done=`` message, and the body template rendered with ``ctx``."""
    return render_template_string(PAGE, body=render_template_string(body_template, **ctx),
                                  flash=request.args.get("done") or "")


@bp.get("")
def overview():
    """Totals and the newest farms."""
    repo = get_repo()
    farms = repo.list("farms")
    rows = sorted((_farm_row(repo, f) for f in farms), key=lambda r: r["created"], reverse=True)
    users = repo.list("users")
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    species = Counter()
    for f in farms:
        for a in repo.list(farm_path(f["id"], "animals")):
            if a.get("status") in ON_FARM_STATUSES:
                species[a.get("species") or "other"] += 1
    from app import ops
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    attention = [
        ("Problems (7 days)", len(ops.problems(repo, days=7)), url_for("admin.problems")),
        ("New accounts (7 days)", sum(1 for u in users if (u.get("created_at") or "") >= week), url_for("admin.users")),
        ("Seen in the apps (7 days)", sum(1 for u in users if (u.get("last_seen") or "") >= week), url_for("admin.apps")),
    ]
    stats = [
        ("Farms", len(farms)), ("New farms (30 days)", sum(1 for f in farms if (f.get("created_at") or "") >= since)),
        ("Users", len(users)), ("Active members", sum(r["members"] for r in rows)),
        ("Waiting for approval", sum(r["pending"] for r in rows)), ("Animals on farms", sum(r["animals"] for r in rows)),
        ("Barns", sum(r["barns"] for r in rows)),
    ]
    return _page("""<h1>Overview</h1><h2>Needs a look</h2><div class="cards">{% for l, n, link in attention %}
<a class="card" href="{{ link }}" style="text-decoration:none;color:inherit"><div class="n">{{ n }}</div><div class="l">{{ l }}</div></a>{% endfor %}</div>
<h2>Totals</h2><div class="cards">{% for l, n in stats %}<div class="card"><div class="n">{{ n }}</div>
<div class="l">{{ l }}</div></div>{% endfor %}</div>
<h2>Animals on farms by species</h2><div class="cards">{% for s, n in species %}<div class="card"><div class="n">{{ n }}</div><div class="l">{{ s }}</div></div>{% else %}<p class="muted">No animals yet.</p>{% endfor %}</div>
<h2>Newest farms</h2>{{ table|safe }}""", stats=stats, attention=attention, species=species.most_common(),
                 table=_farms_table(rows[:10]))


def _farms_table(rows: list[dict]) -> str:
    return render_template_string("""<div class="wrap"><table><tr><th>Farm</th><th>Owner</th><th class="num">Members</th>
<th class="num">Waiting</th><th class="num">Animals</th><th class="num">Barns</th><th>Created</th><th>Last activity</th></tr>
{% for r in rows %}<tr><td><a href="{{ url_for('admin.farm', farm_id=r.id) }}">{{ r.name }}</a><div class="muted">{{ r.address }}</div></td>
<td>{{ r.owner }}</td><td class="num">{{ r.members }}</td><td class="num">{{ r.pending }}</td><td class="num">{{ r.animals }}</td>
<td class="num">{{ r.barns }}</td><td>{{ r.created }}</td><td>{{ r.last_activity }}</td></tr>
{% else %}<tr><td colspan="8" class="muted">No farm.</td></tr>{% endfor %}</table></div>""", rows=rows)


@bp.get("/farms")
def farms():
    """Every farm, searchable by name, id, address or member email."""
    repo = get_repo()
    q = (request.args.get("q") or "").strip().lower()
    rows = []
    for f in repo.list("farms"):
        row = _farm_row(repo, f)
        hay = " ".join([row["id"], row["name"], row["address"]] + [
            f"{m.get('email') or ''} {m.get('name') or ''}" for m in repo.list(members_path(f["id"]))]).lower()
        if not q or q in hay:
            rows.append(row)
    rows.sort(key=lambda r: r["created"], reverse=True)
    return _page("""<h1>Farms ({{ n }})</h1><form class="search" method="get"><input type="search" name="q" value="{{ q }}"
placeholder="Name, address, email or id"><button>Search</button></form>{{ table|safe }}""",
                 n=len(rows), q=request.args.get("q") or "", table=_farms_table(rows))


@bp.get("/farms/<farm_id>")
def farm(farm_id: str):
    """One farm: its members, its animals, barns, last money entries and feed stock (read-only, for support), and
    the delete form."""
    from app import ops

    repo = get_repo()
    f = repo.get("farms", farm_id)
    if not f:
        abort(404)
    members = sorted(repo.list(members_path(farm_id)), key=lambda m: (m.get("status") != "active", m.get("role") or ""))
    counts = [(c, len(repo.list(farm_path(farm_id, c)))) for c in FARM_COLLECTIONS]
    barns = {b["id"]: b for b in repo.list(farm_path(farm_id, "barns"))}
    animals = sorted(repo.list(farm_path(farm_id, "animals")),
                     key=lambda a: (a.get("status") not in ON_FARM_STATUSES, a.get("farm_code") or a.get("ear_tag") or ""))
    on_farm: Counter = Counter(a.get("barn_id") for a in animals if a.get("status") in ON_FARM_STATUSES)
    txs = sorted(repo.list(farm_path(farm_id, "transactions")), key=lambda t: (t.get("date") or "", t.get("created_at") or ""),
                 reverse=True)[:40]
    feeds = repo.list(farm_path(farm_id, "feed_items"))
    moves = repo.list(farm_path(farm_id, "feed_moves"))
    stock = [{"name": i.get("name"), "low_at": i.get("low_at"),
              "left": round(sum(m["sacks"] if m.get("direction") == "in" else -m["sacks"]
                                for m in moves if m.get("feed_id") == i["id"]), 2)} for i in feeds]
    days = sorted(ops.farm_days(repo, farm_id, ops.ACTIVITY_COLLECTIONS), reverse=True)
    view = request.args.get("view") or "animals"
    return _page("""<h1>{{ f.name }}</h1><p class="muted">{{ f.address }} · {{ f.currency }} · id {{ f.id }} · created {{ (f.created_at or '')[:10] }}
· used on {{ days|length }} days{% if days %}, last {{ days[0] }}{% endif %}</p>
<h2>Members</h2><div class="wrap"><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Since</th></tr>
{% for m in members %}<tr><td>{{ m.name or '' }}</td><td>{{ m.email or '' }}</td><td>{{ m.role or '' }}</td><td>{{ m.status }}</td>
<td>{{ (m.decided_at or m.requested_at or '')[:10] }}</td></tr>{% endfor %}</table></div>
<h2>Records</h2><div class="cards">{% for c, n in counts %}<div class="card"><div class="n">{{ n }}</div><div class="l">{{ c }}</div></div>{% endfor %}</div>
<h2>Data</h2><div class="tabs">{% for v, l in [('animals','Animals'),('barns','Barns'),('money','Money'),('feed','Feed stock')] %}
<a class="{{ 'on' if v == view else '' }}" href="?view={{ v }}">{{ l }}</a>{% endfor %}</div>
{% if view == 'animals' %}<div class="wrap"><table><tr><th>Number</th><th>Name</th><th>Species</th><th>Breed</th><th>Sex</th><th>Born</th>
<th>Barn</th><th>Status</th><th>For sale</th></tr>{% for a in animals %}<tr><td>{{ a.farm_code or a.ear_tag }}{% if a.farm_code and a.ear_tag != a.farm_code %}<div class="muted">{{ a.ear_tag }}</div>{% endif %}</td>
<td>{{ a.name or '' }}</td><td>{{ a.species }}</td><td>{{ a.breed or '' }}</td><td>{{ a.sex }}</td><td>{{ a.date_of_birth or a.age_class or '' }}</td>
<td>{{ (barns.get(a.barn_id) or barns.get(a.last_barn_id) or {}).get('name', '') }}</td><td>{{ a.status }}{% if a.status_date %}<div class="muted">{{ a.status_date }}</div>{% endif %}</td>
<td>{% if a.for_sale %}{{ a.asking_price or 'yes' }}{% endif %}</td></tr>{% else %}<tr><td colspan="9" class="muted">No animal.</td></tr>{% endfor %}</table></div>
{% elif view == 'barns' %}<div class="wrap"><table><tr><th>Barn</th><th>Species</th><th class="num">Animals</th><th class="num">Capacity</th></tr>
{% for b in barns.values() %}<tr><td>{{ b.name }}</td><td>{{ (b.species_list or [b.species])|join(', ') if (b.species_list or b.species) else 'any' }}</td>
<td class="num">{{ on_farm.get(b.id, 0) }}</td><td class="num">{{ b.capacity or '' }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No barn.</td></tr>{% endfor %}
<tr><td class="muted">No barn</td><td></td><td class="num">{{ on_farm.get(None, 0) }}</td><td></td></tr></table></div>
{% elif view == 'money' %}<p class="muted">The last 40 entries.</p><div class="wrap"><table><tr><th>Date</th><th>Type</th><th>Category</th><th>Description</th>
<th class="num">Amount</th><th class="num">Animals</th></tr>{% for t in txs %}<tr><td>{{ t.date }}</td><td>{{ t.type }}</td><td>{{ t.category }}</td>
<td>{{ t.description or '' }}</td><td class="num">{{ t.amount }}</td><td class="num">{{ (t.animal_ids or [])|length }}</td></tr>
{% else %}<tr><td colspan="6" class="muted">No entry.</td></tr>{% endfor %}</table></div>
{% else %}<div class="wrap"><table><tr><th>Feed</th><th class="num">Sacks left</th><th class="num">Warn at</th></tr>
{% for i in stock %}<tr><td>{{ i.name }}</td><td class="num">{% if i.left <= (i.low_at or 0) %}<span class="pill red">{{ i.left }}</span>{% else %}{{ i.left }}{% endif %}</td>
<td class="num">{{ i.low_at }}</td></tr>{% else %}<tr><td colspan="3" class="muted">No feed stock kept.</td></tr>{% endfor %}</table></div>{% endif %}
<div class="box danger-box"><h2 style="margin-top:0">Delete this farm</h2>
<p>Deletes the farm, every record above and the animal photos. Its people keep their account (the farm leaves their list). <b>No undo.</b></p>
<form method="post" action="{{ url_for('admin.delete', farm_id=f.id) }}"><input type="hidden" name="token" value="{{ token }}">
<p>Type the farm name <b>{{ f.name }}</b> to confirm:</p><p><input type="text" name="confirm" autocomplete="off" required></p>
<button class="danger">Delete the farm</button></form></div>""", f=f, members=members, counts=counts, token=_token(farm_id),
                 barns=barns, animals=animals, on_farm=on_farm, txs=txs, stock=stock, days=days, view=view)


@bp.post("/farms/<farm_id>/delete")
def delete(farm_id: str):
    """Delete one farm after the typed name and the form token match."""
    repo = get_repo()
    f = repo.get("farms", farm_id)
    if not f:
        abort(404)
    if not hmac.compare_digest(request.form.get("token", ""), _token(farm_id)):
        abort(400)
    if (request.form.get("confirm") or "").strip() != (f.get("name") or f["id"]):
        return _page("""<h1>Not deleted</h1><p>The name did not match. <a href="{{ url_for('admin.farm', farm_id=fid) }}">Back</a></p>""",
                     fid=farm_id), 400
    delete_farm(repo, get_photo_store(), f)
    return redirect(url_for("admin.farms", deleted=f.get("name") or farm_id))


@bp.get("/users")
def users():
    """Every user with their farms, app version and last visit; support actions (resend the verification code,
    mark the email checked)."""
    repo = get_repo()
    q = (request.args.get("q") or "").strip().lower()
    by_uid: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for m in repo.group_list("members"):
        farm_row = repo.get("farms", m.get("parent_id") or "") or {}
        by_uid.setdefault(m["id"], []).append({"farm": farm_row.get("name") or m.get("parent_id"), "farm_id": m.get("parent_id"),
                                               "role": m.get("role"), "status": m.get("status")})
        names[m["id"]] = m.get("email") or names.get(m["id"], "")
    rows = []
    for u in repo.list("users"):
        email = u.get("email") or names.get(u["id"], "")
        row = {"uid": u["id"], "email": email, "name": u.get("name") or "", "lang": u.get("lang") or "",
               "verified": bool(u.get("email_verified")), "created": (u.get("created_at") or "")[:10],
               "farms": by_uid.get(u["id"], []), "platform": u.get("app_platform") or "",
               "version": u.get("app_version") or "", "device": u.get("device_model") or "",
               "os": u.get("os_version") or "", "seen": (u.get("last_seen") or "")[:16].replace("T", " ")}
        hay = f"{row['uid']} {email} {row['name']} {row['device']}".lower()
        if not q or q in hay:
            rows.append(row)
    rows.sort(key=lambda r: r["created"], reverse=True)
    return _page("""<h1>Users ({{ rows|length }})</h1><form class="search" method="get"><input type="search" name="q" value="{{ q }}"
placeholder="Email, name, phone model or uid"><button>Search</button></form><div class="wrap"><table><tr><th>Email</th><th>Name</th><th>Farms</th>
<th>App</th><th>Last seen</th><th>Email checked</th><th>Since</th></tr>{% for r in rows %}<tr><td>{{ r.email }}<div class="muted">{{ r.uid }}</div></td>
<td>{{ r.name }}<div class="muted">{{ r.lang }}</div></td><td>{% for f in r.farms %}<div><a href="{{ url_for('admin.farm', farm_id=f.farm_id) }}">{{ f.farm }}</a> · {{ f.role }} · {{ f.status }}</div>{% else %}<span class="muted">none</span>{% endfor %}</td>
<td>{% if r.platform %}{{ r.platform }} {{ r.version }}<div class="muted">{{ r.device }} {{ r.os }}</div>{% else %}<span class="muted">not known yet</span>{% endif %}</td>
<td>{{ r.seen }}</td>
<td>{% if r.verified %}<span class="pill green">yes</span>{% else %}<span class="pill amber">no</span>
{% if r.email %}<form class="inline" method="post" action="{{ url_for('admin.resend_code', uid=r.uid) }}"><input type="hidden" name="token" value="{{ token }}">
<button class="small">Resend code</button></form>{% endif %}
<form class="inline" method="post" action="{{ url_for('admin.mark_verified', uid=r.uid) }}"><input type="hidden" name="token" value="{{ token }}">
<button class="small" style="background:#5B6B69">Mark checked</button></form>{% endif %}</td>
<td>{{ r.created }}</td></tr>{% else %}<tr><td colspan="7" class="muted">No user.</td></tr>{% endfor %}</table></div>""",
                 rows=rows, q=request.args.get("q") or "", token=_form_token("support"))


from app.admin import pages  # noqa: E402,F401  (the other pages register on the same blueprint)
