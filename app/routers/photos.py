"""Public photo download by unguessable id (/v1/photos/<id>)."""

from __future__ import annotations

from flask import Blueprint, Response

from app.deps import get_photo_store
from app.errors import ApiError
from app.services.photos import ALLOWED_TYPES

bp = Blueprint("photos", __name__)


@bp.get("/photos/<file_id>")
def get_photo(file_id: str):
    """Public, unguessable photo URL (so image loaders need no auth header). GridFS and MinIO storage."""
    store = get_photo_store()
    read = getattr(store, "read", None)
    result = read(file_id) if read else None
    if result is None:
        raise ApiError(404, "Photo not found")
    content, content_type = result
    if content_type not in ALLOWED_TYPES:  # never serve anything else from this public URL
        content_type = "application/octet-stream"
    return Response(content, mimetype=content_type, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",  # browsers must not guess another type (e.g. HTML)
    })
