"""Request dependencies: authentication (identity), farm membership and role context, and the lazily created
database, push and photo services."""

from __future__ import annotations

import os
from pathlib import Path

from dataclasses import dataclass
from functools import lru_cache

from flask import current_app, g, request

from app.config import ENV_FILE, get_settings
from app.errors import ApiError
from app.permissions import at_least, required_role
from app.repository import FirestoreRepository, MongoRepository, Repository
from app.services.mailer import LogMailer, Mailer, MailjetMailer
from app.services.notifier import FcmNotifier, Notifier
from app.services import membership as membership_service
from app.services.membership import Identity
from app.services.photos import FirebasePhotoStore, GridFsPhotoStore, MinioPhotoStore, PhotoStore


def _override(name: str):
    """Tests inject fakes through create_app(overrides={...}); production never sets any."""
    return current_app.config.get("FARMIVO_OVERRIDES", {}).get(name)


@lru_cache
def _firebase_app():
    """Initialise Firebase Admin once (project id, optional storage bucket and service-account key)."""
    import firebase_admin

    settings = get_settings()
    options = {}
    if settings.firebase_project_id:
        options["projectId"] = settings.firebase_project_id
    if settings.firebase_storage_bucket:
        options["storageBucket"] = settings.firebase_storage_bucket
    # Firebase Admin needs the service-account key even to verify sign-in tokens.
    # FARMIVO_FIREBASE_CREDENTIALS (path in .env, relative to the project folder) wins over
    # GOOGLE_APPLICATION_CREDENTIALS (environment variable, e.g. from supervisor).
    credential = None
    if settings.firebase_credentials:
        from firebase_admin import credentials

        key_path = Path(settings.firebase_credentials)
        if not key_path.is_absolute():
            key_path = ENV_FILE.parent / key_path
        if not key_path.is_file():
            raise RuntimeError(f"Firebase key not found: {key_path} (FARMIVO_FIREBASE_CREDENTIALS)")
        credential = credentials.Certificate(str(key_path))
    elif not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        current_app.logger.error(
            "No Firebase service-account key: set FARMIVO_FIREBASE_CREDENTIALS in .env. "
            "Every sign-in token will be rejected until then."
        )
    return firebase_admin.initialize_app(credential, options=options or None)


@lru_cache
def _mongo_db():
    """Open the MongoDB database once (5 s timeouts). Raises RuntimeError for invalid settings."""
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
    """The process-wide repository: Firestore if FARMIVO_DB_BACKEND=firestore, else MongoDB."""
    if get_settings().db_backend == "firestore":
        from firebase_admin import firestore

        return FirestoreRepository(firestore.client(_firebase_app()))
    return MongoRepository(_mongo_db(), get_settings().mongo_prefix)


@lru_cache
def _notifier() -> Notifier:
    """The process-wide push sender (Firebase Cloud Messaging)."""
    _firebase_app()
    return FcmNotifier()


@lru_cache
def _photo_store() -> PhotoStore:
    """The process-wide photo store: MinIO, Firebase Storage or GridFS, depending on settings."""
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
    return GridFsPhotoStore(_mongo_db(), settings.public_base_url, f"{settings.mongo_prefix}photos")


def get_repo() -> Repository:
    """Repository for this request (test override or the shared one)."""
    return _override("repo") or _repo()


def get_notifier() -> Notifier:
    """Push notifier for this request (test override or FCM)."""
    return _override("notifier") or _notifier()


@lru_cache
def _mailer() -> Mailer:
    """The process-wide mailer: Mailjet when MAILJET_API_KEY is set, otherwise codes go to the log."""
    s = get_settings()
    if not s.mailjet_api_key:
        return LogMailer()
    return MailjetMailer(s.mailjet_api_key, s.mailjet_api_secret, s.mail_from_email, s.mail_from_name, s.mail_timeout)


def get_mailer() -> Mailer:
    """Mailer for this request (test override or the configured one)."""
    return _override("mailer") or _mailer()


def get_photo_store() -> PhotoStore:
    """Photo store for this request (test override or the configured store)."""
    return _override("photo_store") or _photo_store()


def get_identity() -> Identity:
    """Verify the Firebase ID token (Authorization: Bearer ...) and return who is calling (uid, email, name).

    Used directly by the onboarding endpoints (/me, /farms, /farms/join, /devices), which work before the
    user belongs to a farm. Tests set the caller with create_app(overrides={"uid": ..., "email": ...}).
    """
    cached = g.get("farmivo_identity")
    if cached is not None:
        return cached
    forced = _override("uid")
    if forced:
        identity = Identity(uid=forced, email=_override("email"), name=_override("name"),
                            email_verified=bool(_override("email_verified")))
    else:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(401, "Missing bearer token")
        from firebase_admin import auth

        try:
            _firebase_app()
            decoded = auth.verify_id_token(token.strip())
        except Exception as exc:  # noqa: BLE001
            # The reason (wrong project, expired, clock skew, ...) goes to the log, never to the client.
            current_app.logger.warning("Rejected Firebase token: %s", exc)
            raise ApiError(401, "Invalid or expired token") from exc
        identity = Identity(uid=decoded["uid"], email=decoded.get("email"), name=decoded.get("name"),
                            email_verified=bool(decoded.get("email_verified")))
    g.farmivo_identity = identity
    return identity


def get_current_uid() -> str:
    """The signed-in user's Firebase uid (see :func:`get_identity`)."""
    return get_identity().uid


@dataclass
class Ctx:
    """Per-request context of an active farm member: who, which farm, which role, and the repository."""
    uid: str
    farm_id: str
    repo: Repository
    role: str = "owner"
    farm: dict | None = None

    def require(self, minimum: str) -> None:
        """Raise 403 (code forbidden_role) unless the caller's role is ``minimum`` or more powerful."""
        if not at_least(self.role, minimum):
            raise ApiError(403, f"Your role ({self.role}) does not allow this", code="forbidden_role")


def get_ctx() -> Ctx:
    """Authenticate the request, require an ACTIVE farm membership and check the role for this route.

    403 codes the apps route on: ``no_farm`` (create or join a farm), ``pending`` (waiting for approval),
    ``rejected`` (request refused) and ``forbidden_role`` (the role may not call this route; the policy is
    :func:`app.permissions.required_role`).
    """
    cached = g.get("farmivo_ctx")
    if cached is not None:
        return cached
    identity = get_identity()
    repo = get_repo()
    membership = membership_service.resolve(repo, identity)
    farm_name = (membership.farm or {}).get("name") or "the farm"
    if membership.status == "pending":
        raise ApiError(403, f"Your request to join {farm_name} is waiting for approval", code="pending")
    if membership.status == "rejected":
        raise ApiError(403, f"Your request to join {farm_name} was rejected", code="rejected")
    if membership.status != "active" or not membership.farm:
        raise ApiError(403, "You are not a member of a farm yet", code="no_farm")
    ctx = Ctx(uid=identity.uid, farm_id=membership.farm["id"], repo=repo, role=membership.role or "viewer",
              farm=membership.farm)
    ctx.require(required_role(request.method, request.path))
    g.farmivo_ctx = ctx
    return ctx
