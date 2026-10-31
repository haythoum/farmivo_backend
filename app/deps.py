from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from flask import current_app, g, request

from app.config import get_settings
from app.errors import ApiError
from app.repository import FirestoreRepository, MongoRepository, Repository
from app.services.notifier import FcmNotifier, Notifier
from app.services.photos import FirebasePhotoStore, GridFsPhotoStore, MinioPhotoStore, PhotoStore


def _override(name: str):
    """Tests inject fakes through create_app(overrides={...}); production never sets any."""
    return current_app.config.get("FARMIVO_OVERRIDES", {}).get(name)


@lru_cache
def _firebase_app():
    import firebase_admin

    settings = get_settings()
    options = {}
    if settings.firebase_project_id:
        options["projectId"] = settings.firebase_project_id
    if settings.firebase_storage_bucket:
        options["storageBucket"] = settings.firebase_storage_bucket
    # Credentials come from GOOGLE_APPLICATION_CREDENTIALS or the runtime service account.
    return firebase_admin.initialize_app(options=options or None)


@lru_cache
def _mongo_db():
    from pymongo import MongoClient
    from pymongo.errors import ConfigurationError

    settings = get_settings()
    try:
        client = MongoClient(settings.mongo_url, tz_aware=True, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    except ConfigurationError as exc:
        raise RuntimeError(
            f"MongoDB settings are invalid ({exc}). Check FARMIVO_MONGO_HOST/PORT/USER/PASSWORD or FARMIVO_MONGO_URI in .env"
        ) from exc
    return client[settings.mongo_db]


@lru_cache
def _repo() -> Repository:
    if get_settings().db_backend == "firestore":
        from firebase_admin import firestore

        return FirestoreRepository(firestore.client(_firebase_app()))
    return MongoRepository(_mongo_db())


@lru_cache
def _notifier() -> Notifier:
    _firebase_app()
    return FcmNotifier()


@lru_cache
def _photo_store() -> PhotoStore:
    settings = get_settings()
    if settings.photo_store == "minio":
        if not (settings.minio_access_key and settings.minio_secret_key):
            raise RuntimeError("FARMIVO_MINIO_ACCESS_KEY and FARMIVO_MINIO_SECRET_KEY are required for the minio photo store")
        return MinioPhotoStore(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
            settings.minio_secure,
            settings.public_base_url,
        )
    if settings.db_backend == "firestore":
        _firebase_app()
        return FirebasePhotoStore(settings.firebase_storage_bucket)
    return GridFsPhotoStore(_mongo_db(), settings.public_base_url)


def get_repo() -> Repository:
    return _override("repo") or _repo()


def get_notifier() -> Notifier:
    return _override("notifier") or _notifier()


def get_photo_store() -> PhotoStore:
    return _override("photo_store") or _photo_store()


def get_current_uid() -> str:
    """Verify the Firebase ID token (Authorization: Bearer ...) sent by the mobile app and return the uid."""
    forced = _override("uid")
    if forced:
        return forced
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "Missing bearer token")
    from firebase_admin import auth

    _firebase_app()
    try:
        decoded = auth.verify_id_token(token.strip())
    except Exception as exc:  # noqa: BLE001
        # The reason (wrong project, expired, clock skew, ...) goes to the log, never to the client.
        current_app.logger.warning("Rejected Firebase token: %s", exc)
        raise ApiError(401, "Invalid or expired token") from exc
    return decoded["uid"]


@dataclass
class Ctx:
    uid: str
    farm_id: str
    repo: Repository


def get_ctx() -> Ctx:
    """Authenticate the request and resolve (creating on first use) the farm of the signed-in user."""
    cached = g.get("farmivo_ctx")
    if cached is not None:
        return cached
    uid = get_current_uid()
    repo = get_repo()
    user = repo.get("users", uid)
    if user and user.get("farm_id"):
        ctx = Ctx(uid=uid, farm_id=user["farm_id"], repo=repo)
    else:
        farm_id = uuid.uuid4().hex
        repo.create(
            "farms",
            {"name": "My Farm", "currency": "USD", "owner_uid": uid, "member_uids": [uid]},
            doc_id=farm_id,
        )
        repo.set("users", uid, {"farm_id": farm_id})
        ctx = Ctx(uid=uid, farm_id=farm_id, repo=repo)
    g.farmivo_ctx = ctx
    return ctx
