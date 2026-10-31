from __future__ import annotations

import uuid
from typing import Protocol

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class PhotoStore(Protocol):
    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        """Store an image and return its URL."""
        ...


class MemoryPhotoStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        key = f"farms/{farm_id}/animals/{animal_id}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
        self.files[key] = content
        return f"https://storage.test/{key}"


class FirebasePhotoStore:
    def __init__(self, bucket_name: str | None) -> None:
        self._bucket_name = bucket_name

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        from firebase_admin import storage

        bucket = storage.bucket(self._bucket_name)
        blob = bucket.blob(f"farms/{farm_id}/animals/{animal_id}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}")
        blob.upload_from_string(content, content_type=content_type)
        blob.make_public()
        return blob.public_url


class GridFsPhotoStore:
    """Stores photos in MongoDB (GridFS) and serves them through GET /v1/photos/{id}."""

    def __init__(self, db, public_base_url: str) -> None:
        import gridfs

        self._fs = gridfs.GridFS(db, collection="photos")
        self._base = public_base_url.rstrip("/")

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        file_id = self._fs.put(content, content_type=content_type, farm_id=farm_id, animal_id=animal_id)
        return f"{self._base}/v1/photos/{file_id}"

    def read(self, file_id: str) -> tuple[bytes, str] | None:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            f = self._fs.get(ObjectId(file_id))
        except (InvalidId, Exception):  # noqa: BLE001 - not found / malformed id
            return None
        return f.read(), f.content_type or "image/jpeg"
