"""In-app notification history (/v1/notifications...)."""

from __future__ import annotations

from flask import Blueprint

from app.deps import get_ctx
from app.errors import ApiError
from app.i18n import request_lang
from app.routers.crud import path_of
from app.schemas import NotificationOut
from app.services.reminders import notification_text, visible_notifications
from app.web import no_content, out, q_bool, q_int

bp = Blueprint("notifications", __name__)


@bp.get("/notifications")
def list_notifications():
    """GET /v1/notifications - newest first, optionally unread only."""
    ctx = get_ctx()
    unread_only = q_bool("unread_only")
    limit = q_int("limit", 50, ge=1, le=200)
    filters = [("read", "==", False)] if unread_only else None
    rows = ctx.repo.list(path_of(ctx, "notifications"), filters, order_by="created_at", desc=True)
    rows = visible_notifications(rows, ctx.role)[:limit]
    return out([NotificationOut.model_validate(notification_text(r, request_lang())) for r in rows])


@bp.post("/notifications/read-all")
def mark_all_read():
    """POST /v1/notifications/read-all - mark every unread notification as read."""
    ctx = get_ctx()
    for n in visible_notifications(ctx.repo.list(path_of(ctx, "notifications"), [("read", "==", False)]), ctx.role):
        ctx.repo.update(path_of(ctx, "notifications"), n["id"], {"read": True})
    return no_content()


@bp.post("/notifications/<notification_id>/read")
def mark_read(notification_id: str):
    """POST /v1/notifications/<id>/read - mark one notification as read."""
    ctx = get_ctx()
    record = ctx.repo.update(path_of(ctx, "notifications"), notification_id, {"read": True})
    if not record:
        raise ApiError(404, "Notification not found")
    return out(NotificationOut.model_validate(notification_text(record, request_lang())))


@bp.delete("/notifications/<notification_id>")
def delete_notification(notification_id: str):
    """DELETE /v1/notifications/<id> - delete one notification."""
    ctx = get_ctx()
    if not ctx.repo.delete(path_of(ctx, "notifications"), notification_id):
        raise ApiError(404, "Notification not found")
    return no_content()
