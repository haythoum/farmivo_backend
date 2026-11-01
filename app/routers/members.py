"""Who the user is and which farm they belong to: onboarding (create or join a farm) and member management.

Onboarding endpoints work without a farm (they use :func:`app.deps.get_identity`):
``GET /v1/me``, ``POST /v1/me/verification/send``, ``POST /v1/me/verification/verify``, ``POST /v1/farms``,
``POST /v1/farms/join``, ``DELETE /v1/me/membership``. Creating or joining a farm needs a verified email
(the 6-digit code, see :mod:`app.services.verification`).

Member management needs an active manager or owner (enforced by :func:`app.deps.get_ctx` through
:func:`app.permissions.required_role`): ``/v1/farm/members...``, ``/v1/farm/invite-code`` and, owner only,
``/v1/farm/transfer-ownership``. See docs/ROLES_AND_MEMBERS.md.
"""
from __future__ import annotations

from flask import Blueprint, current_app, request

from app.config import get_settings
from app.deps import get_ctx, get_identity, get_mailer, get_notifier, get_repo
from app.errors import ApiError
from app.schemas import (
    ApproveIn, FarmCreate, InviteCodeOut, JoinIn, MemberOut, MeOut, RoleIn, TransferIn, VerificationSentOut, VerifyIn,
)
from app.services import membership, verification
from app.web import body, no_content, out

bp = Blueprint("members", __name__)


def _me(identity, state) -> MeOut:
    verified = verification.is_verified(get_repo(), identity, state)
    return MeOut.model_validate(membership.me_payload(identity, state, verified))


def _require_verified(identity) -> None:
    """Creating or joining a farm needs a verified email (403 email_unverified)."""
    if not verification.is_verified(get_repo(), identity):
        raise ApiError(403, "Verify your email first", code="email_unverified")


@bp.get("/me")
def me():
    """GET /v1/me - status none | pending | active | rejected, the role and the farm. Call it after sign-in."""
    identity = get_identity()
    return out(_me(identity, membership.resolve(get_repo(), identity)))


@bp.post("/me/verification/send")
def send_verification_code():
    """POST /v1/me/verification/send - email a new 6-digit code (60 s between codes, 5 per hour)."""
    identity = get_identity()
    sent = verification.send_code(get_repo(), get_mailer(), identity, get_settings().code_hash_secret)
    return out(VerificationSentOut.model_validate(sent))


@bp.post("/me/verification/verify")
def verify_email():
    """POST /v1/me/verification/verify {"code"} - confirm the emailed code; returns /me with email_verified true."""
    identity = get_identity()
    verification.verify_code(get_repo(), identity, body(VerifyIn).code, get_settings().code_hash_secret)
    _mark_firebase_verified(identity.uid)
    return out(_me(identity, membership.resolve(get_repo(), identity)))


def _mark_firebase_verified(uid: str) -> None:
    """Best effort: also set emailVerified in Firebase Auth. Failures are logged, never returned."""
    if current_app.config.get("FARMIVO_OVERRIDES", {}).get("uid"):
        return  # tests: no Firebase
    try:
        from firebase_admin import auth

        from app.deps import _firebase_app

        _firebase_app()
        auth.update_user(uid, email_verified=True)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("Could not mark the email verified in Firebase for %s: %s", uid, exc)


@bp.post("/farms")
def create_farm():
    """POST /v1/farms - create a farm and become its owner (201). 409 if already in or waiting for a farm,
    403 email_unverified before the email code was confirmed."""
    identity = get_identity()
    _require_verified(identity)
    data = body(FarmCreate).model_dump(exclude_none=True)
    return out(_me(identity, membership.create_farm(get_repo(), identity, data)), 201)


@bp.post("/farms/join")
def join_farm():
    """POST /v1/farms/join - ask to join the farm with this invite code; waits for approval (status pending).
    403 email_unverified before the email code was confirmed."""
    identity = get_identity()
    _require_verified(identity)
    code = body(JoinIn).invite_code
    state = membership.request_to_join(get_repo(), get_notifier(), identity, code)
    return out(_me(identity, state))


@bp.delete("/me/membership")
def leave_farm():
    """DELETE /v1/me/membership - cancel a pending request or leave the farm (owner: transfer first, 409)."""
    identity = get_identity()
    return out(_me(identity, membership.leave(get_repo(), identity)))


@bp.get("/farm/members")
def list_members():
    """GET /v1/farm/members - pending requests first, then active members (manager or owner)."""
    ctx = get_ctx()
    return out([MemberOut.model_validate(m) for m in membership.list_members(ctx.repo, ctx.farm_id)])


@bp.post("/farm/members/<uid>/approve")
def approve_member(uid: str):
    """POST /v1/farm/members/<uid>/approve - accept a request; optional body {"role": manager|worker|viewer}."""
    ctx = get_ctx()
    role = body(ApproveIn).role if request.get_data() else "worker"
    member = membership.approve(ctx.repo, get_notifier(), ctx.farm, uid, role, ctx.uid)
    return out(MemberOut.model_validate(member))


@bp.post("/farm/members/<uid>/reject")
def reject_member(uid: str):
    """POST /v1/farm/members/<uid>/reject - refuse a pending request."""
    ctx = get_ctx()
    member = membership.reject(ctx.repo, get_notifier(), ctx.farm, uid, ctx.uid)
    return out(MemberOut.model_validate(member))


@bp.patch("/farm/members/<uid>")
def change_member_role(uid: str):
    """PATCH /v1/farm/members/<uid> {"role"} - change an active member's role (not the owner's)."""
    ctx = get_ctx()
    member = membership.change_role(ctx.repo, ctx.farm_id, uid, body(RoleIn).role, ctx.uid)
    return out(MemberOut.model_validate(member))


@bp.delete("/farm/members/<uid>")
def remove_member(uid: str):
    """DELETE /v1/farm/members/<uid> - remove a member or a pending request (never the owner)."""
    ctx = get_ctx()
    membership.remove(ctx.repo, ctx.farm_id, uid)
    return no_content()


@bp.post("/farm/invite-code")
def rotate_invite_code():
    """POST /v1/farm/invite-code - new invite code; the old one stops working."""
    ctx = get_ctx()
    return out(InviteCodeOut(invite_code=membership.rotate_invite_code(ctx.repo, ctx.farm)))


@bp.post("/farm/transfer-ownership")
def transfer_ownership():
    """POST /v1/farm/transfer-ownership {"uid"} - owner only; the old owner becomes a manager."""
    ctx = get_ctx()
    new_owner = membership.transfer_ownership(ctx.repo, ctx.farm, ctx.uid, body(TransferIn).uid)
    return out(MemberOut.model_validate(new_owner))
