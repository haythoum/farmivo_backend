from __future__ import annotations

from flask import Flask, jsonify
from flask_cors import CORS

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import animals, breeding, dashboard, farm, finance, growth, health, internal, notifications, photos, reports

API_PREFIX = "/v1"


def create_app(overrides: dict | None = None) -> Flask:
    """Application factory. ``overrides`` (repo, notifier, photo_store, uid) is used by the tests only."""
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    settings = get_settings()
    app.config["FARMIVO_OVERRIDES"] = overrides or {}
    app.config["MAX_CONTENT_LENGTH"] = settings.max_photo_bytes + 1024 * 1024  # photo + multipart overhead

    if settings.cors_origin_list:
        CORS(app, origins=settings.cors_origin_list)

    register_error_handlers(app)
    if "repo" not in app.config["FARMIVO_OVERRIDES"] and settings.db_backend == "mongo":
        log_mongo_target(app, settings)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    for module in (
        farm,
        animals,
        health,
        growth,
        finance,
        dashboard,
        notifications,
        photos,
        reports,
        internal,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)
    app.register_blueprint(breeding.bp, url_prefix=f"{API_PREFIX}/breedings")
    app.register_blueprint(health.reminders_bp, url_prefix=API_PREFIX)
    app.register_blueprint(growth.growth_bp, url_prefix=API_PREFIX)
    return app


def log_mongo_target(app: Flask, settings) -> None:
    """Say at startup which MongoDB the API will use (never the password), or what is wrong with the settings."""
    from urllib.parse import urlsplit

    url = settings.mongo_url
    try:
        parts = urlsplit(url)
        host = parts.hostname if "," not in parts.netloc else parts.netloc.rpartition("@")[2]
        user = parts.username
    except ValueError as exc:
        app.logger.error("MongoDB settings are invalid (%s). Check FARMIVO_MONGO_* in .env", exc)
        return
    if not parts.scheme.startswith("mongodb") or not host:
        app.logger.error("MongoDB settings are invalid: no host found. Check FARMIVO_MONGO_* in .env "
                         "(a password with @ : / # ? must be URL-encoded in FARMIVO_MONGO_URI, "
                         "or use FARMIVO_MONGO_PASSWORD instead)")
        return
    from app.config import ENV_FILE

    source = str(ENV_FILE) if ENV_FILE.exists() else f"{ENV_FILE} NOT FOUND, using defaults"
    app.logger.warning("Settings file: %s", source)
    app.logger.warning("MongoDB: %s, database %s, user %s", host, settings.mongo_db, user or "(none)")


# WSGI entry point: gunicorn 'app.main:app'
app = create_app()
