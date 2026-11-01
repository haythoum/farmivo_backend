"""API error type and JSON error handlers. Every error body has the shape {"detail": ...}."""
from __future__ import annotations

import json

from flask import Flask, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """An error returned to the client as JSON {"detail": ...} with the given HTTP status."""
    def __init__(self, status: int, detail) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


def validation_error(exc: ValidationError) -> ApiError:
    """Turn a pydantic ValidationError into a 422 ApiError carrying the list of field errors."""
    return ApiError(422, json.loads(exc.json(include_url=False)))


def register_error_handlers(app: Flask) -> None:
    """Make every error (ApiError, HTTP errors, unexpected exceptions) answer JSON {"detail": ...}."""
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify({"detail": exc.detail}), exc.status

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # e.g. 404 unknown route, 405, 413 body too large
        return jsonify({"detail": exc.name}), exc.code or 500

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        from pymongo.errors import PyMongoError

        app.logger.exception("Unhandled error")
        if isinstance(exc, PyMongoError):
            return jsonify({"detail": "Database unavailable"}), 503
        return jsonify({"detail": "Internal server error"}), 500
