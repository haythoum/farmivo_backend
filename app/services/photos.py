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
