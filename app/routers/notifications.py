from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.deps import Ctx, get_ctx
from app.routers.crud import path_of
from app.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    ctx: Ctx = Depends(get_ctx),
):
    filters = [("read", "==", False)] if unread_only else None
    rows = ctx.repo.list(path_of(ctx, "notifications"), filters, order_by="created_at", desc=True, limit=limit)
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(ctx: Ctx = Depends(get_ctx)):
    for n in ctx.repo.list(path_of(ctx, "notifications"), [("read", "==", False)]):
        ctx.repo.update(path_of(ctx, "notifications"), n["id"], {"read": True})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, ctx: Ctx = Depends(get_ctx)):
    record = ctx.repo.update(path_of(ctx, "notifications"), notification_id, {"read": True})
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return NotificationOut.model_validate(record)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: str, ctx: Ctx = Depends(get_ctx)):
    if not ctx.repo.delete(path_of(ctx, "notifications"), notification_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
