from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# The .env file next to the app/ folder, whatever directory the server is started from.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FARMIVO_", env_file=ENV_FILE, extra="ignore")

    firebase_project_id: str | None = None
    firebase_storage_bucket: str | None = None
    # Path to the Firebase service-account key JSON (absolute, or relative to this project folder).
    firebase_credentials: str | None = None
    # "mongo" (default: MongoDB for data and photos) or "firestore"
    db_backend: str = "mongo"
    # MongoDB: either the separate fields below (simplest, the password needs no escaping)
    # or one full connection string in mongo_uri, which then wins.
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_user: str | None = None
    mongo_password: str | None = None
    mongo_auth_db: str | None = None  # database where the user was created; defaults to mongo_db
    mongo_uri: str | None = None
    mongo_db: str = "farmivo"
    # Used to build absolute photo URLs when photos are stored in MongoDB (GridFS)
    public_base_url: str = "http://localhost:8000"
    # Where photos live: "gridfs" (inside the Mongo database, default) or "minio" (S3-compatible bucket)
    photo_store: str = "gridfs"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "farmivo-photos"
    minio_secure: bool = False
    cron_secret: str | None = None
    cors_origins: str = ""
    environment: str = "development"

    # Reminder buckets: a reminder notifies once when it enters each bucket
    # (days before the due date). -1 means overdue.
    max_photo_bytes: int = 5 * 1024 * 1024

    @property
    def mongo_url(self) -> str:
        if self.mongo_uri:
            return self.mongo_uri.strip().strip('"').strip("'")
        if not self.mongo_user:
            return f"mongodb://{self.mongo_host}:{self.mongo_port}"
        from urllib.parse import quote_plus

        credentials = f"{quote_plus(self.mongo_user)}:{quote_plus(self.mongo_password or '')}"
        auth_db = self.mongo_auth_db or self.mongo_db
        return f"mongodb://{credentials}@{self.mongo_host}:{self.mongo_port}/?authSource={quote_plus(auth_db)}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
