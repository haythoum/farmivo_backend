"""API error type and JSON error handlers. Every error body has the shape {"detail": ...}."""
from __future__ import annotations

import json

from flask import Flask, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, status: int, detail) -> None:
        super().__init__(str(detail))
        self.status = status
        self.detail = detail


def validation_error(exc: ValidationError) -> ApiError:
    return ApiError(422, json.loads(exc.json(include_url=False)))


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return jsonify({"detail": exc.detail}), exc.status

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        # e.g. 404 unknown route, 405, 413 body too large
        return jsonify({"detail": exc.name}), exc.code or 500
