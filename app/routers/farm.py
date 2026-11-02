"""The signed-in user's farm settings and push devices (/v1/farm, /v1/devices).

Creating and joining farms, and managing members, live in app/routers/members.py.
"""

from __future__ import annotations

from flask import Blueprint

from app.deps import Ctx, get_ctx, get_identity, get_repo
from app.errors import ApiError
from app.i18n import request_lang, request_lang_given
from app.permissions import at_least
from app.services.membership import ensure_invite_code
from app.schemas import DeviceIn, FarmOut, FarmUpdate
from app.web import body, no_content, out, q_str

bp = Blueprint("farm", __name__)


def render_farm(ctx: Ctx, farm: dict) -> FarmOut:
    """The farm with the caller's role; the invite code only for managers and the owner."""
    if at_least(ctx.role, "manager"):
        farm = ensure_invite_code(ctx.repo, farm)
    data = {**farm, "role": ctx.role}
    if not at_least(ctx.role, "manager"):
        data["invite_code"] = None
    return FarmOut.model_validate(data)


@bp.get("/farm")
def get_farm():
    """GET /v1/farm - the caller's farm, their role and (manager or owner) the invite code."""
    ctx = get_ctx()
    return out(render_farm(ctx, ctx.repo.get("farms", ctx.farm_id)))


@bp.patch("/farm")
def update_farm():
    """PATCH /v1/farm - change name, currency, country or address (manager or owner)."""
    ctx = get_ctx()
    patch = body(FarmUpdate).model_dump(exclude_unset=True, exclude_none=True)
    farm = ctx.repo.update("farms", ctx.farm_id, patch) if patch else ctx.repo.get("farms", ctx.farm_id)
    return out(render_farm(ctx, farm))


@bp.post("/devices")
def register_device():
    """Register (or refresh) the FCM token of this phone so it receives pushes.

    Works before the user belongs to a farm, so someone waiting for approval is told when they are accepted.
    """
    uid, repo = get_identity().uid, get_repo()
    data = body(DeviceIn)
    language = data.language or (request_lang() if request_lang_given() else None)
    fields = {"platform": data.platform}
    if language:
        fields["language"] = language
    path = f"users/{uid}/devices"
    for existing in repo.list(path, [("token", "==", data.token)]):
        repo.update(path, existing["id"], fields)
        return no_content()
    repo.create(path, {"token": data.token, **fields})
    return no_content()


@bp.delete("/devices")
def unregister_device():
    """Call on sign-out so the phone stops receiving this user's notifications (works without a farm too)."""
    uid, repo = get_identity().uid, get_repo()
    token = q_str("token")
    if not token:
        raise ApiError(422, [{"loc": ["query", "token"], "msg": "Field required", "type": "missing"}])
    path = f"users/{uid}/devices"
    for existing in repo.list(path, [("token", "==", token)]):
        repo.delete(path, existing["id"])
    return no_content()
