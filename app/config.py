from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FARMIVO_", env_file=".env", extra="ignore")

    firebase_project_id: str | None = None
    firebase_storage_bucket: str | None = None
    # "mongo" (default: MongoDB for data and photos) or "firestore"
    db_backend: str = "mongo"
    mongo_uri: str = "mongodb://localhost:27017"
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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
