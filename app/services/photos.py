"""Photo storage backends. Each save() returns the URL stored in the animal's photo_url."""

from __future__ import annotations

import uuid
from typing import Protocol

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class PhotoStore(Protocol):
    """Interface of a photo store."""
    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        """Store an image and return its URL."""
        ...


class MemoryPhotoStore:
    """Keeps photos in memory (tests)."""
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        key = f"farms/{farm_id}/animals/{animal_id}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
        self.files[key] = content
        return f"https://storage.test/{key}"


class FirebasePhotoStore:
    """Uploads photos to Firebase Storage and returns their public URL (Firestore setup only)."""
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

    def __init__(self, db, public_base_url: str, collection: str = "photos") -> None:
        import gridfs

        self._fs = gridfs.GridFS(db, collection=collection)
        self._base = public_base_url.rstrip("/")

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        file_id = self._fs.put(content, content_type=content_type, farm_id=farm_id, animal_id=animal_id)
        return f"{self._base}/v1/photos/{file_id}"

    def read(self, file_id: str) -> tuple[bytes, str] | None:
        """Return (bytes, content type) of a stored photo, or None if the id is unknown or malformed."""
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            f = self._fs.get(ObjectId(file_id))
        except (InvalidId, Exception):  # noqa: BLE001 - not found / malformed id
            return None
        return f.read(), f.content_type or "image/jpeg"


class MinioPhotoStore:
    """Stores photos in a private MinIO (S3) bucket; they are served through GET /v1/photos/{id}.

    The bucket never has to be public: the API streams the object back, so a dedicated
    access key limited to this bucket is enough.
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool, public_base_url: str) -> None:
        from minio import Minio

        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._base = public_base_url.rstrip("/")
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        import io

        file_id = uuid.uuid4().hex
        self._client.put_object(
            self._bucket,
            file_id,
            io.BytesIO(content),
            len(content),
            content_type=content_type,
            metadata={"farm-id": farm_id, "animal-id": animal_id},
        )
        return f"{self._base}/v1/photos/{file_id}"

    def read(self, file_id: str) -> tuple[bytes, str] | None:
        """Return (bytes, content type) of a stored photo, or None if the id is unknown or malformed."""
        import re

        if not re.fullmatch(r"[0-9a-f]{32}", file_id):
            return None
        try:
            response = self._client.get_object(self._bucket, file_id)
        except Exception:  # noqa: BLE001 - missing object / transport error
            return None
        try:
            return response.read(), response.headers.get("Content-Type") or "image/jpeg"
        finally:
            response.close()
            response.release_conn()
