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


# WSGI entry point: gunicorn 'app.main:app'
app = create_app()
