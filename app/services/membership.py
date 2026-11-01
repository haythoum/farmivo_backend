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
from app.services.reminders import notify_farm, push_to_users

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
    """Write the ``users/<uid>`` record (farm and status), keeping the email-verified flag stored there.

    ``farm_id=None`` means the user no longer has a farm (left, removed).
    """
    keep = {k: v for k, v in (repo.get("users", uid) or {}).items() if k in ("email_verified", "email_verified_at")}
    fields = {**keep, "farm_id": farm_id, "status": status} if farm_id else keep
    if fields:
        repo.set("users", uid, fields)
    else:
        repo.delete("users", uid)


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

def resolve(repo: Repository, identity: Identity) -> Membership:
    """Find the user's farm and membership. Also upgrades legacy accounts and fills in a missing email/name."""
    uid = identity.uid
    user = repo.get("users", uid)
    if not user or not user.get("farm_id"):
        return Membership("none")
    farm = repo.get("farms", user["farm_id"])
    if not farm:
        return Membership("none")
    member = repo.get(members_path(farm["id"]), uid)
    if member is None:
        # Account from before memberships: its own farm makes it the owner (another listed member: manager).
        if farm.get("owner_uid") != uid and uid not in (farm.get("member_uids") or []):
            return Membership("none")
        role = "owner" if farm.get("owner_uid") == uid else "manager"
        stamp = now_iso()
        member = repo.set(members_path(farm["id"]), uid, {
            "uid": uid, "email": identity.email, "name": identity.name, "role": role, "status": "active",
            "requested_at": stamp, "decided_at": stamp, "decided_by": uid,
        })
        set_user(repo, uid, farm["id"], "active")
    elif (identity.email and not member.get("email")) or (identity.name and not member.get("name")):
        member = repo.update(members_path(farm["id"]), uid, {
            "email": member.get("email") or identity.email, "name": member.get("name") or identity.name,
        }) or member
    return Membership(member.get("status", "none"), farm, member)


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
    farm = find_farm_by_code(repo, code)
    if not farm:
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
        title=f"{who} wants to join",
        body=f"{who} asked to join {farm.get('name', 'your farm')}. Open Members to approve or reject.",
        type_="join_request",
        roles={"owner", "manager"},
    )
    return Membership("pending", farm, member)


def leave(repo: Repository, identity: Identity) -> Membership:
    """Cancel a pending request or leave the farm. The owner must transfer ownership first (409)."""
    current = resolve(repo, identity)
    if current.status == "none" or not current.farm:
        return Membership("none")
    if current.role == "owner":
        raise ApiError(409, "Transfer ownership first")
    repo.delete(members_path(current.farm["id"]), identity.uid)
    set_user(repo, identity.uid, None, None)
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
    member = _decide(repo, farm["id"], uid, decided_by, status="active", role=role)
    set_user(repo, uid, farm["id"], "active")
    name = farm.get("name", "the farm")
    push_to_users(repo, notifier, [uid], f"Welcome to {name}", f"You can now use {name} in Farmivo.",
                  {"type": "membership_approved"})
    return member


def reject(repo: Repository, notifier: Notifier, farm: dict, uid: str, decided_by: str) -> dict:
    """Refuse a pending request. The person sees "rejected" and can create a farm or ask again."""
    member = _get_member(repo, farm["id"], uid)
    if member["status"] != "pending":
        raise ApiError(409, "This person is not waiting for approval")
    member = _decide(repo, farm["id"], uid, decided_by, status="rejected")
    set_user(repo, uid, farm["id"], "rejected")
    push_to_users(repo, notifier, [uid], "Request not accepted",
                  f"Your request to join {farm.get('name', 'the farm')} was not accepted.",
                  {"type": "membership_rejected"})
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
