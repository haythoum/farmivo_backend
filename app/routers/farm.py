"""The signed-in user's farm and push devices (/v1/farm, /v1/devices)."""

from __future__ import annotations

from flask import Blueprint

from app.deps import get_ctx
from app.errors import ApiError
from app.schemas import DeviceIn, FarmOut, FarmUpdate
from app.web import body, no_content, out, q_str

bp = Blueprint("farm", __name__)


@bp.get("/farm")
def get_farm():
    """GET /v1/farm - the farm of the signed-in user (created automatically on first use)."""
    ctx = get_ctx()
    return out(FarmOut.model_validate(ctx.repo.get("farms", ctx.farm_id)))


@bp.patch("/farm")
def update_farm():
    """PATCH /v1/farm - change name, currency, country or address."""
    ctx = get_ctx()
    patch = body(FarmUpdate).model_dump(exclude_unset=True, exclude_none=True)
    farm = ctx.repo.update("farms", ctx.farm_id, patch) if patch else ctx.repo.get("farms", ctx.farm_id)
    return out(FarmOut.model_validate(farm))


@bp.post("/devices")
def register_device():
    """Register (or refresh) the FCM token of this phone so it receives push reminders."""
    ctx = get_ctx()
    data = body(DeviceIn)
    path = f"users/{ctx.uid}/devices"
    for existing in ctx.repo.list(path, [("token", "==", data.token)]):
        ctx.repo.update(path, existing["id"], {"platform": data.platform})
        return no_content()
    ctx.repo.create(path, {"token": data.token, "platform": data.platform})
    return no_content()


@bp.delete("/devices")
def unregister_device():
    """Call on sign-out so the phone stops receiving this user's notifications."""
    ctx = get_ctx()
    token = q_str("token")
    if not token:
        raise ApiError(422, [{"loc": ["query", "token"], "msg": "Field required", "type": "missing"}])
    path = f"users/{ctx.uid}/devices"
    for existing in ctx.repo.list(path, [("token", "==", token)]):
        ctx.repo.delete(path, existing["id"])
    return no_content()
