"""Small request/response helpers shared by the blueprints."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, TypeVar

from flask import Response, jsonify, request
from pydantic import BaseModel, ValidationError

from app.errors import ApiError, validation_error

M = TypeVar("M", bound=BaseModel)


def body(model: type[M]) -> M:
    """Parse the JSON request body into a pydantic model (422 on bad input)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(422, "Request body must be a JSON object")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise validation_error(exc) from exc


def out(value: Any, status: int = 200) -> Response:
    """Serialise a pydantic model, a list of models or plain JSON data."""

    def conv(v: Any) -> Any:
        if isinstance(v, BaseModel):
            return v.model_dump(mode="json")
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    response = jsonify(conv(value))
    response.status_code = status
    return response


def no_content() -> Response:
    return Response(status=204)


# ------------------------------------------------------------ query string
def _bad(name: str, msg: str) -> ApiError:
    return ApiError(422, [{"loc": ["query", name], "msg": msg, "type": "value_error"}])


def q_str(name: str, default: str | None = None) -> str | None:
    value = request.args.get(name)
    return value if value not in (None, "") else default


def q_int(name: str, default: int | None = None, ge: int | None = None, le: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise _bad(name, "Input should be a valid integer") from None
    if ge is not None and value < ge:
        raise _bad(name, f"Input should be greater than or equal to {ge}")
    if le is not None and value > le:
        raise _bad(name, f"Input should be less than or equal to {le}")
    return value


def q_bool(name: str, default: bool = False) -> bool:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    if raw.lower() in ("1", "true", "yes", "on", "t", "y"):
        return True
    if raw.lower() in ("0", "false", "no", "off", "f", "n"):
        return False
    raise _bad(name, "Input should be a valid boolean")


def q_date(name: str) -> date | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _bad(name, "Input should be a valid date (YYYY-MM-DD)") from None


def q_enum(name: str, enum: type[Enum], default: Enum | None = None, required: bool = False):
    raw = request.args.get(name)
    if raw in (None, ""):
        if required:
            raise _bad(name, "Field required")
        return default
    try:
        return enum(raw)
    except ValueError:
        raise _bad(name, f"Input should be one of: {', '.join(str(e.value) for e in enum)}") from None
