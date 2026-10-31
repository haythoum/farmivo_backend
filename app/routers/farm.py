from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.deps import Ctx, get_ctx
from app.schemas import DeviceIn, FarmOut, FarmUpdate

router = APIRouter(tags=["Farm"])


@router.get("/farm", response_model=FarmOut)
def get_farm(ctx: Ctx = Depends(get_ctx)):
    return FarmOut.model_validate(ctx.repo.get("farms", ctx.farm_id))


@router.patch("/farm", response_model=FarmOut)
def update_farm(body: FarmUpdate, ctx: Ctx = Depends(get_ctx)):  # type: ignore[valid-type]
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    farm = ctx.repo.update("farms", ctx.farm_id, patch) if patch else ctx.repo.get("farms", ctx.farm_id)
    return FarmOut.model_validate(farm)


@router.post("/devices", status_code=status.HTTP_204_NO_CONTENT, tags=["Notifications"])
def register_device(body: DeviceIn, ctx: Ctx = Depends(get_ctx)):
    """Register (or refresh) the FCM token of this phone so it receives push reminders."""
    path = f"users/{ctx.uid}/devices"
    for existing in ctx.repo.list(path, [("token", "==", body.token)]):
        ctx.repo.update(path, existing["id"], {"platform": body.platform})
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    ctx.repo.create(path, {"token": body.token, "platform": body.platform})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/devices", status_code=status.HTTP_204_NO_CONTENT, tags=["Notifications"])
def unregister_device(token: str, ctx: Ctx = Depends(get_ctx)):
    """Call on sign-out so the phone stops receiving this user's notifications."""
    path = f"users/{ctx.uid}/devices"
    for existing in ctx.repo.list(path, [("token", "==", token)]):
        ctx.repo.delete(path, existing["id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
