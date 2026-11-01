"""Who the user is and which farm they belong to: onboarding (create or join a farm) and member management.

Onboarding endpoints work without a farm (they use :func:`app.deps.get_identity`):
``GET /v1/me``, ``POST /v1/farms``, ``POST /v1/farms/join``, ``DELETE /v1/me/membership``.

Member management needs an active manager or owner (enforced by :func:`app.deps.get_ctx` through
:func:`app.permissions.required_role`): ``/v1/farm/members...``, ``/v1/farm/invite-code`` and, owner only,
``/v1/farm/transfer-ownership``. See docs/ROLES_AND_MEMBERS.md.
"""
from __future__ import annotations

from flask import Blueprint, request

from app.deps import get_ctx, get_identity, get_notifier, get_repo
from app.schemas import ApproveIn, FarmCreate, InviteCodeOut, JoinIn, MemberOut, MeOut, RoleIn, TransferIn
from app.services import membership
from app.web import body, no_content, out

bp = Blueprint("members", __name__)


def _me(identity, state) -> MeOut:
    return MeOut.model_validate(membership.me_payload(identity, state))


@bp.get("/me")
def me():
    """GET /v1/me - status none | pending | active | rejected, the role and the farm. Call it after sign-in."""
    identity = get_identity()
    return out(_me(identity, membership.resolve(get_repo(), identity)))


@bp.post("/farms")
def create_farm():
    """POST /v1/farms - create a farm and become its owner (201). 409 if already in or waiting for a farm."""
    identity = get_identity()
    data = body(FarmCreate).model_dump(exclude_none=True)
    return out(_me(identity, membership.create_farm(get_repo(), identity, data)), 201)


@bp.post("/farms/join")
def join_farm():
    """POST /v1/farms/join - ask to join the farm with this invite code; waits for approval (status pending)."""
    identity = get_identity()
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
