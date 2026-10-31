from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.repository import FirestoreRepository, Repository
from app.services.notifier import FcmNotifier, Notifier
from app.services.photos import FirebasePhotoStore, PhotoStore

bearer = HTTPBearer(auto_error=False)


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
def get_repo() -> Repository:
    from firebase_admin import firestore

    return FirestoreRepository(firestore.client(_firebase_app()))


@lru_cache
def get_notifier() -> Notifier:
    _firebase_app()
    return FcmNotifier()


@lru_cache
def get_photo_store() -> PhotoStore:
    _firebase_app()
    return FirebasePhotoStore(get_settings().firebase_storage_bucket)


def get_current_uid(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    """Verify the Firebase ID token sent by the mobile app and return the user's uid."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    from firebase_admin import auth

    _firebase_app()
    try:
        decoded = auth.verify_id_token(creds.credentials)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return decoded["uid"]


@dataclass
class Ctx:
    uid: str
    farm_id: str
    repo: Repository


def get_ctx(uid: str = Depends(get_current_uid), repo: Repository = Depends(get_repo)) -> Ctx:
    """Resolve (and on first use create) the farm that belongs to the signed-in user."""
    user = repo.get("users", uid)
    if user and user.get("farm_id"):
        return Ctx(uid=uid, farm_id=user["farm_id"], repo=repo)
    farm_id = uuid.uuid4().hex
    repo.create(
        "farms",
        {"name": "My Farm", "currency": "USD", "owner_uid": uid, "member_uids": [uid]},
        doc_id=farm_id,
    )
    repo.set("users", uid, {"farm_id": farm_id})
    return Ctx(uid=uid, farm_id=farm_id, repo=repo)
