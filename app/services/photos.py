"""Photo storage backends. Each save() returns the URL stored in the animal's photo_url."""

from __future__ import annotations

import re
import uuid
from typing import Protocol

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

# Photo ids in URLs are random 32-hex strings, so a photo URL cannot be guessed from another one.
_RANDOM_ID = re.compile(r"[0-9a-f]{32}")


def photo_id(url: str | None) -> str | None:
    """The id at the end of a ``.../v1/photos/<id>`` URL, or None."""
    if not url or "/v1/photos/" not in url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1] or None


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

    def delete_farm(self, farm_id: str, urls: list[str]) -> None:
        """Delete every photo of a farm."""
        for key in [k for k in self.files if k.startswith(f"farms/{farm_id}/")]:
            del self.files[key]

    def delete(self, url: str) -> None:
        """Delete one photo by its URL (replaced photo or deleted animal)."""
        self.files.pop(url.replace("https://storage.test/", ""), None)


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

    def delete_farm(self, farm_id: str, urls: list[str]) -> None:
        """Delete every photo of a farm (all blobs under farms/<farm_id>/)."""
        from firebase_admin import storage

        for blob in storage.bucket(self._bucket_name).list_blobs(prefix=f"farms/{farm_id}/"):
            blob.delete()

    def delete(self, url: str) -> None:
        """Delete one photo by its public URL."""
        from firebase_admin import storage

        marker = f"/{self._bucket_name}/" if self._bucket_name else None
        if marker and marker in url:
            storage.bucket(self._bucket_name).blob(url.split(marker, 1)[1]).delete()


class GridFsPhotoStore:
    """Stores photos in MongoDB (GridFS) and serves them through GET /v1/photos/{id}."""

    def __init__(self, db, public_base_url: str, collection: str = "photos") -> None:
        import gridfs

        self._fs = gridfs.GridFS(db, collection=collection)
        self._base = public_base_url.rstrip("/")

    def save(self, farm_id: str, animal_id: str, content: bytes, content_type: str) -> str:
        # A random id (not GridFS's default ObjectId, which is time-based and guessable).
        file_id = uuid.uuid4().hex
        self._fs.put(content, _id=file_id, content_type=content_type, farm_id=farm_id, animal_id=animal_id)
        return f"{self._base}/v1/photos/{file_id}"

    def delete(self, url: str) -> None:
        """Delete one photo by its URL (replaced photo or deleted animal)."""
        file_id = photo_id(url)
        if file_id and _RANDOM_ID.fullmatch(file_id):
            self._fs.delete(file_id)
        elif file_id:
            from bson import ObjectId
            from bson.errors import InvalidId

            try:
                self._fs.delete(ObjectId(file_id))
            except InvalidId:
                pass

    def delete_farm(self, farm_id: str, urls: list[str]) -> None:
        """Delete every photo of a farm, including replaced ones (each file carries its farm_id)."""
        for stored in self._fs.find({"farm_id": farm_id}):
            self._fs.delete(stored._id)

    def read(self, file_id: str) -> tuple[bytes, str] | None:
        """Return (bytes, content type) of a stored photo, or None if the id is unknown or malformed."""
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            # New photos have random string ids; photos stored before that keep their ObjectId.
            key = file_id if _RANDOM_ID.fullmatch(file_id) else ObjectId(file_id)
            f = self._fs.get(key)
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

    def delete_farm(self, farm_id: str, urls: list[str]) -> None:
        """Delete the farm's current animal photos (the object id is the last part of each photo URL)."""
        import re

        for url in urls:
            self.delete(url)

    def delete(self, url: str) -> None:
        """Delete one photo by its URL (replaced photo or deleted animal)."""
        file_id = photo_id(url)
        if file_id and _RANDOM_ID.fullmatch(file_id):
            self._client.remove_object(self._bucket, file_id)

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
