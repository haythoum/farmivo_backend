from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import get_photo_store

router = APIRouter(tags=["Photos"])


@router.get("/photos/{file_id}")
def get_photo(file_id: str, store=Depends(get_photo_store)):
    """Public, unguessable photo URL (so image loaders need no auth header). Only with MongoDB storage."""
    read = getattr(store, "read", None)
    result = read(file_id) if read else None
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    content, content_type = result
    return Response(content, media_type=content_type, headers={"Cache-Control": "public, max-age=31536000, immutable"})
