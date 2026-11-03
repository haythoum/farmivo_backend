"""Farm membership: who belongs to which farm, with which role, and the join-request workflow.

Storage (repository paths, see docs/DATA_MODEL.md):

- ``farms/<farm_id>/members/<uid>`` (Mongo collection ``members``): one record per person and farm with
  ``role`` (owner, manager, worker, viewer) and ``status`` (pending, active, rejected).
- ``users/<uid>`` (collection ``users``): ``farm_id`` and ``status`` of the user's current farm, and
  ``email_verified`` once the email code was confirmed. No ``farm_id`` means the user has no farm yet.
- ``farms/<farm_id>``: ``owner_uid`` and the ``invite_code`` people use to ask to join.

A person belongs to at most one farm at a time. Accounts created before memberships existed (a ``users``
document pointing at a farm they own, but no member record) are turned into an active owner the first time
they are seen; see :func:`resolve`.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from app.errors import ApiError
from app.repository import Repository, farm_path, now_iso
from app.services.notifier import Notifier
from app.services.notifier import MEMBERS_CHANNEL
from app.services.reminders import notify_farm, push_to_users, resolve_join_requests

# Letters and digits that cannot be confused when read aloud or typed (no 0/O, 1/I/L).
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


@dataclass
class Identity:
    """The signed-in person, taken from the Firebase ID token (``email_verified`` is the token's claim)."""
    uid: str
    email: str | None = None
    name: str | None = None
    email_verified: bool = False


@dataclass
class Membership:
    """Where a user stands: ``status`` is none, pending, active or rejected."""
    status: str
    farm: dict | None = None
    member: dict | None = None

    @property
    def role(self) -> str | None:
        """The role, only while the membership is active."""
        return self.member["role"] if self.status == "active" and self.member else None


def set_user(repo: Repository, uid: str, farm_id: str | None, status: str | None) -> None:
    """Point ``users/<uid>`` at the user's farm and status (``farm_id=None``: no farm any more).

    Only these two fields change; everything else stored there (email_verified, lang, ...) is kept.
    """
    if repo.get("users", uid) is None:
        if farm_id:
            repo.set("users", uid, {"farm_id": farm_id, "status": status})
        return
    repo.update("users", uid, {"farm_id": farm_id, "status": status if farm_id else None})


def members_path(farm_id: str) -> str:
    """Repository path of a farm's member records."""
    return farm_path(farm_id, "members")


# ------------------------------------------------------------------ invite codes

def code_prefix(farm_name: str) -> str:
    """Three letters from the farm name: initials for 3+ words ("Green Valley Farm" -> GVF), else the first
    letters ("My Farm" -> MYF). Names without Latin letters get FRM."""
    words = re.findall(r"[A-Za-z]+", farm_name or "")
    letters = "".join(w[0] for w in words) if len(words) >= 3 else "".join(words)
    return (letters.upper() + "FRM")[:3]


def normalize_code(text: str) -> str:
    """Accept codes typed with any case, spaces or without the dash: " gvf 7k3p " -> "GVF-7K3P"."""
    compact = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    return f"{compact[:3]}-{compact[3:]}" if len(compact) == 7 else compact


def find_farm_by_code(repo: Repository, code: str) -> dict | None:
    """The farm whose invite code is ``code`` (normalised first), or None."""
    code = normalize_code(code)
    if not code:
        return None
    matches = repo.list("farms", [("invite_code", "==", code)])
    return matches[0] if matches else None


def new_invite_code(repo: Repository, farm_name: str) -> str:
    """A fresh code like "GVF-7K3P" that no other farm uses."""
    prefix = code_prefix(farm_name)
    rng = random.SystemRandom()
    while True:
        code = f"{prefix}-{''.join(rng.choice(CODE_ALPHABET) for _ in range(4))}"
        if not repo.list("farms", [("invite_code", "==", code)]):
            return code


def ensure_invite_code(repo: Repository, farm: dict) -> dict:
    """Give a farm created before invite codes existed its code; returns the (updated) farm."""
    if farm.get("invite_code"):
        return farm
    return repo.update("farms", farm["id"], {"invite_code": new_invite_code(repo, farm.get("name", ""))}) or farm


# ------------------------------------------------------------------ reading

def remember_lang(repo: Repository, uid: str, lang: str) -> None:
    """Store the language of the user's last request on ``users/<uid>`` (used for their pushes and emails)."""
    user = repo.get("users", uid)
    if user is None:
        repo.set("users", uid, {"lang": lang})
    elif user.get("lang") != lang:
        repo.update("users", uid, {"lang": lang})


STATUS_ORDER = {"active": 0, "pending": 1, "rejected": 2}


def _find_member(repo: Repository, uid: str) -> tuple[dict, dict] | None:
    """(farm, member record) of the user's membership in any farm: active first, then pending, then the latest
    rejection. Used when ``users/<uid>`` does not lead to a member record."""
    rows = [m for m in repo.group_list("members", [("uid", "==", uid)]) if m.get("status") in STATUS_ORDER]
    rows.sort(key=lambda m: m.get("decided_at") or m.get("requested_at") or "", reverse=True)  # newest first
    rows.sort(key=lambda m: STATUS_ORDER[m["status"]])  # stable: active, pending, rejected
    for member in rows:
        farm = repo.get("farms", member.get("parent_id") or "")
        if farm:
            member = {k: v for k, v in member.items() if k != "parent_id"}
            return farm, member
    return None


def resolve(repo: Repository, identity: Identity) -> Membership:
    """Find the user's farm and membership. The member record is the source of truth: ``users/<uid>`` is only
    a pointer to it and is repaired when it disagrees (missing, wrong farm, stale status). Also upgrades legacy
    accounts (a farm they own but no member record) and fills in a missing email/name."""
    uid = identity.uid
    user = repo.get("users", uid) or {}
    farm = repo.get("farms", user["farm_id"]) if user.get("farm_id") else None
    member = repo.get(members_path(farm["id"]), uid) if farm else None

    if member is None and farm and (farm.get("owner_uid") == uid or uid in (farm.get("member_uids") or [])):
        # Account from before memberships: its own farm makes it the owner (another listed member: manager).
        role = "owner" if farm.get("owner_uid") == uid else "manager"
        stamp = now_iso()
        member = repo.set(members_path(farm["id"]), uid, {
            "uid": uid, "email": identity.email, "name": identity.name, "role": role, "status": "active",
            "requested_at": stamp, "decided_at": stamp, "decided_by": uid,
        })
    if member is None or member.get("status") not in STATUS_ORDER:
        found = _find_member(repo, uid)
        if found is None:
            if user.get("farm_id"):
                set_user(repo, uid, None, None)  # pointer to a farm that no longer knows this user
            return Membership("none")
        farm, member = found

    status = member["status"]
    if user.get("farm_id") != farm["id"] or user.get("status") != status:
        set_user(repo, uid, farm["id"], status)  # self-heal the pointer
    if (identity.email and not member.get("email")) or (identity.name and not member.get("name")):
        member = repo.update(members_path(farm["id"]), uid, {
            "email": member.get("email") or identity.email, "name": member.get("name") or identity.name,
        }) or member
    return Membership(status, farm, member)


def me_payload(identity: Identity, membership: Membership, email_verified: bool = False) -> dict:
    """The body of GET /v1/me (and of the onboarding calls)."""
    farm = membership.farm
    return {
        "email_verified": email_verified,
        "uid": identity.uid,
        "email": identity.email,
        "status": membership.status,
        "role": membership.role,
        "farm": {"id": farm["id"], "name": farm.get("name")} if farm and membership.status != "none" else None,
    }


def list_members(repo: Repository, farm_id: str) -> list[dict]:
    """Pending requests first (oldest first), then active members (owner, managers, workers, viewers, by name)."""
    from app.permissions import RANK

    rows = repo.list(members_path(farm_id))
    pending = sorted((m for m in rows if m.get("status") == "pending"), key=lambda m: m.get("requested_at") or "")
    active = sorted(
        (m for m in rows if m.get("status") == "active"),
        key=lambda m: (-RANK.get(m.get("role"), 0), (m.get("name") or m.get("email") or "").lower()),
    )
    return pending + active


def label(member: dict) -> str:
    """How a person is named in messages: name, else email, else "Someone"."""
    return member.get("name") or member.get("email") or "Someone"


# ------------------------------------------------------------------ onboarding (no farm required)

def create_farm(repo: Repository, identity: Identity, data: dict) -> Membership:
    """Create a farm with the caller as its active owner. 409 if the caller already has or awaits a farm."""
    current = resolve(repo, identity)
    if current.status == "active":
        raise ApiError(409, "You already belong to a farm")
    if current.status == "pending":
        raise ApiError(409, "You already asked to join a farm. Cancel that request first")
    farm = repo.create("farms", {
        **data,
        "currency": (data.get("currency") or "USD").upper(),
        "owner_uid": identity.uid,
        "invite_code": new_invite_code(repo, data["name"]),
    })
    stamp = now_iso()
    member = repo.set(members_path(farm["id"]), identity.uid, {
        "uid": identity.uid, "email": identity.email, "name": identity.name, "role": "owner", "status": "active",
        "requested_at": stamp, "decided_at": stamp, "decided_by": identity.uid,
    })
    set_user(repo, identity.uid, farm["id"], "active")
    return Membership("active", farm, member)


def request_to_join(repo: Repository, notifier: Notifier, identity: Identity, code: str) -> Membership:
    """Ask to join the farm with this invite code. The request waits for a manager or the owner.

    A pending request to another farm is replaced; a rejected one can be repeated. 404 for an unknown code,
    409 if the caller is already an active member somewhere.
    """
    current = resolve(repo, identity)
    if current.status == "active":
        raise ApiError(409, "You already belong to a farm. Leave it first")
    recent_failures = _recent_join_failures(repo, identity.uid)
    if len(recent_failures) >= MAX_JOIN_FAILURES_PER_HOUR:
        raise ApiError(429, "Too many wrong codes. Try again in an hour", code="too_many_attempts")
    farm = find_farm_by_code(repo, code)
    if not farm:
        # Remember wrong codes so nobody can try all codes to find farms.
        fields = {"join_failures": recent_failures + [now_iso()]}
        if repo.update("users", identity.uid, fields) is None:
            repo.set("users", identity.uid, fields)
        raise ApiError(404, "No farm with this code")
    if current.status == "pending" and current.farm and current.farm["id"] != farm["id"]:
        repo.delete(members_path(current.farm["id"]), identity.uid)
    stamp = now_iso()
    member = repo.set(members_path(farm["id"]), identity.uid, {
        "uid": identity.uid, "email": identity.email, "name": identity.name, "role": "worker", "status": "pending",
        "requested_at": stamp, "decided_at": None, "decided_by": None,
    })
    set_user(repo, identity.uid, farm["id"], "pending")
    who = label(member)
    notify_farm(
        repo, notifier, farm,
        title_key="push.join.title",
        body_key="push.join.body",
        params={"who": who, "farm": farm.get("name", "")},
        type_="join_request",
        roles={"owner", "manager"},
        channel=MEMBERS_CHANNEL,
        subject_uid=identity.uid,
    )
    return Membership("pending", farm, member)


MAX_JOIN_FAILURES_PER_HOUR = 10


def _recent_join_failures(repo: Repository, uid: str) -> list[str]:
    """Times (ISO, UTC) of this user's wrong invite codes in the last hour."""
    from datetime import datetime, timedelta, timezone

    limit = datetime.now(timezone.utc) - timedelta(hours=1)
    times = (repo.get("users", uid) or {}).get("join_failures") or []
    return [t for t in times if datetime.fromisoformat(t) > limit]


def leave(repo: Repository, identity: Identity) -> Membership:
    """Cancel a pending request or leave the farm. The owner must transfer ownership first (409)."""
    current = resolve(repo, identity)
    if current.status == "none" or not current.farm:
        return Membership("none")
    if current.role == "owner":
        raise ApiError(409, "Transfer ownership first")
    repo.delete(members_path(current.farm["id"]), identity.uid)
    set_user(repo, identity.uid, None, None)
    resolve_join_requests(repo, current.farm["id"], identity.uid)  # a cancelled request needs no answer
    return Membership("none")


# ------------------------------------------------------------------ managing members (manager or owner)

def _get_member(repo: Repository, farm_id: str, uid: str) -> dict:
    member = repo.get(members_path(farm_id), uid)
    if not member or member.get("status") == "rejected":
        raise ApiError(404, "Member not found")
    return member


def _decide(repo: Repository, farm_id: str, uid: str, decided_by: str, **fields) -> dict:
    return repo.update(members_path(farm_id), uid, {**fields, "decided_at": now_iso(), "decided_by": decided_by})  # type: ignore[return-value]


def approve(repo: Repository, notifier: Notifier, farm: dict, uid: str, role: str, decided_by: str) -> dict:
    """Accept a pending request with the given role (manager, worker or viewer) and tell the person by push."""
    member = _get_member(repo, farm["id"], uid)
    if member["status"] != "pending":
        raise ApiError(409, "This person is not waiting for approval")
    # Compare-and-set: of two managers approving (or rejecting) at the same moment, only one wins.
    member = repo.update_where(members_path(farm["id"]), uid, {"status": "pending"},
                               {"status": "active", "role": role, "decided_at": now_iso(), "decided_by": decided_by})
    if member is None:
        raise ApiError(409, "This person is not waiting for approval")
    set_user(repo, uid, farm["id"], "active")
    resolve_join_requests(repo, farm["id"], uid)
    # Stored as the new member's personal notification (they can now read the farm's list) and pushed with its id.
    notify_farm(repo, notifier, farm, title_key="push.approved.title", body_key="push.approved.body",
                params={"farm": farm.get("name", "")}, type_="membership_approved", channel=MEMBERS_CHANNEL,
                for_uid=uid)
    return member


def reject(repo: Repository, notifier: Notifier, farm: dict, uid: str, decided_by: str) -> dict:
    """Refuse a pending request. The person sees "rejected" and can create a farm or ask again."""
    member = _get_member(repo, farm["id"], uid)
    if member["status"] != "pending":
        raise ApiError(409, "This person is not waiting for approval")
    member = repo.update_where(members_path(farm["id"]), uid, {"status": "pending"},
                               {"status": "rejected", "decided_at": now_iso(), "decided_by": decided_by})
    if member is None:
        raise ApiError(409, "This person is not waiting for approval")
    set_user(repo, uid, farm["id"], "rejected")
    resolve_join_requests(repo, farm["id"], uid)
    # The person is not a member, so nothing is stored in the farm's list: push only (no notification_id).
    push_to_users(repo, notifier, [uid], "push.rejected.title", "push.rejected.body", {"farm": farm.get("name", "")},
                  {"type": "membership_rejected", "farm_id": farm["id"]})
    return member


def change_role(repo: Repository, farm_id: str, uid: str, role: str, decided_by: str) -> dict:
    """Set an active member's role (manager, worker or viewer). The owner's role only changes by transfer."""
    member = _get_member(repo, farm_id, uid)
    if member["status"] != "active":
        raise ApiError(409, "Approve the request first")
    if member["role"] == "owner":
        raise ApiError(409, "The owner's role changes only by transferring ownership")
    return _decide(repo, farm_id, uid, decided_by, role=role)


def remove(repo: Repository, farm_id: str, uid: str) -> None:
    """Remove a member or a pending request. The owner cannot be removed."""
    member = _get_member(repo, farm_id, uid)
    if member["role"] == "owner" and member["status"] == "active":
        raise ApiError(409, "The owner cannot be removed")
    repo.delete(members_path(farm_id), uid)
    set_user(repo, uid, None, None)
    resolve_join_requests(repo, farm_id, uid)


def rotate_invite_code(repo: Repository, farm: dict) -> str:
    """Give the farm a new invite code; the old one stops working immediately."""
    code = new_invite_code(repo, farm.get("name", ""))
    repo.update("farms", farm["id"], {"invite_code": code})
    return code


def transfer_ownership(repo: Repository, farm: dict, from_uid: str, to_uid: str) -> dict:
    """Make another active member the owner; the previous owner becomes a manager. Returns the new owner."""
    if to_uid == from_uid:
        raise ApiError(409, "You are already the owner")
    target = _get_member(repo, farm["id"], to_uid)
    if target["status"] != "active":
        raise ApiError(409, "The new owner must be an active member")
    _decide(repo, farm["id"], from_uid, from_uid, role="manager")
    new_owner = _decide(repo, farm["id"], to_uid, from_uid, role="owner")
    repo.update("farms", farm["id"], {"owner_uid": to_uid})
    return new_owner
