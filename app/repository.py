"""Storage abstraction.

All data lives in Firestore, addressed by slash-separated collection paths such as
``farms/{farm_id}/animals``. The ``Repository`` protocol has two implementations:

* ``MongoRepository``     - production (MongoDB / Atlas). Default.
* ``FirestoreRepository`` - production alternative (Firebase).
* ``InMemoryRepository``  - tests and local experiments (no Firebase needed).

Only equality filters are pushed down to Firestore. Range filters, ordering and limits
are applied in Python. A single farm holds at most a few thousand documents per
collection, and this keeps the project free of composite-index management.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

Filter = tuple[str, str, Any]  # (field, op, value); op in ==, !=, <, <=, >, >=, in


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _matches(doc: dict, flt: Filter) -> bool:
    field, op, value = flt
    actual = doc.get(field)
    if op == "in":
        return actual in value
    if actual is None:
        return op == "!=" and value is not None
    try:
        if op == "==":
            return actual == value
        if op == "!=":
            return actual != value
        if op == "<":
            return actual < value
        if op == "<=":
            return actual <= value
        if op == ">":
            return actual > value
        if op == ">=":
            return actual >= value
    except TypeError:
        return False
    raise ValueError(f"Unsupported filter operator: {op}")


def apply_query(
    docs: list[dict],
    filters: list[Filter] | None = None,
    order_by: str | None = None,
    desc: bool = False,
    limit: int | None = None,
) -> list[dict]:
    result = [d for d in docs if all(_matches(d, f) for f in (filters or []))]
    if order_by:
        present = [d for d in result if d.get(order_by) is not None]
        missing = [d for d in result if d.get(order_by) is None]
        present.sort(key=lambda d: d[order_by], reverse=desc)
        result = present + missing
    if limit is not None:
        result = result[:limit]
    return result


class Repository(Protocol):
    def get(self, path: str, doc_id: str) -> dict | None: ...

    def list(
        self,
        path: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict]: ...

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict: ...

    def update(self, path: str, doc_id: str, data: dict) -> dict | None: ...

    def set(self, path: str, doc_id: str, data: dict) -> dict: ...

    def delete(self, path: str, doc_id: str) -> bool: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}

    def _col(self, path: str) -> dict[str, dict]:
        return self._data.setdefault(path, {})

    def get(self, path: str, doc_id: str) -> dict | None:
        doc = self._col(path).get(doc_id)
        return {**copy.deepcopy(doc), "id": doc_id} if doc is not None else None

    def list(self, path, filters=None, order_by=None, desc=False, limit=None) -> list[dict]:
        docs = [{**copy.deepcopy(d), "id": i} for i, d in self._col(path).items()]
        return apply_query(docs, filters, order_by, desc, limit)

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict:
        doc_id = doc_id or uuid.uuid4().hex
        stamp = now_iso()
        self._col(path)[doc_id] = {**copy.deepcopy(data), "created_at": stamp, "updated_at": stamp}
        return self.get(path, doc_id)  # type: ignore[return-value]

    def update(self, path: str, doc_id: str, data: dict) -> dict | None:
        col = self._col(path)
        if doc_id not in col:
            return None
        col[doc_id].update(copy.deepcopy(data))
        col[doc_id]["updated_at"] = now_iso()
        return self.get(path, doc_id)

    def set(self, path: str, doc_id: str, data: dict) -> dict:
        col = self._col(path)
        created = col.get(doc_id, {}).get("created_at") or now_iso()
        col[doc_id] = {**copy.deepcopy(data), "created_at": created, "updated_at": now_iso()}
        return self.get(path, doc_id)  # type: ignore[return-value]

    def delete(self, path: str, doc_id: str) -> bool:
        return self._col(path).pop(doc_id, None) is not None


class FirestoreRepository:
    def __init__(self, client: Any) -> None:
        self._db = client

    @staticmethod
    def _to_dict(snap: Any) -> dict:
        return {**(snap.to_dict() or {}), "id": snap.id}

    def get(self, path: str, doc_id: str) -> dict | None:
        snap = self._db.collection(path).document(doc_id).get()
        return self._to_dict(snap) if snap.exists else None

    def list(self, path, filters=None, order_by=None, desc=False, limit=None) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query: Any = self._db.collection(path)
        remaining: list[Filter] = []
        for flt in filters or []:
            if flt[1] == "==":
                query = query.where(filter=FieldFilter(*flt))
            else:
                remaining.append(flt)
        docs = [self._to_dict(s) for s in query.stream()]
        return apply_query(docs, remaining, order_by, desc, limit)

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict:
        doc_id = doc_id or uuid.uuid4().hex
        stamp = now_iso()
        self._db.collection(path).document(doc_id).set({**data, "created_at": stamp, "updated_at": stamp})
        return self.get(path, doc_id)  # type: ignore[return-value]

    def update(self, path: str, doc_id: str, data: dict) -> dict | None:
        ref = self._db.collection(path).document(doc_id)
        if not ref.get().exists:
            return None
        ref.update({**data, "updated_at": now_iso()})
        return self.get(path, doc_id)

    def set(self, path: str, doc_id: str, data: dict) -> dict:
        ref = self._db.collection(path).document(doc_id)
        existing = ref.get()
        created = (existing.to_dict() or {}).get("created_at") if existing.exists else None
        ref.set({**data, "created_at": created or now_iso(), "updated_at": now_iso()})
        return self.get(path, doc_id)  # type: ignore[return-value]

    def delete(self, path: str, doc_id: str) -> bool:
        ref = self._db.collection(path).document(doc_id)
        if not ref.get().exists:
            return False
        ref.delete()
        return True


class MongoRepository:
    """All documents live in one collection, ``docs``; the Firestore-style path is stored in ``_path``."""

    def __init__(self, db: Any) -> None:
        self._c = db["docs"]
        self._c.create_index("_path")

    @staticmethod
    def _out(raw: dict) -> dict:
        doc = {k: v for k, v in raw.items() if k not in ("_id", "_path", "_doc_id")}
        doc["id"] = raw["_doc_id"]
        return doc

    @staticmethod
    def _key(path: str, doc_id: str) -> str:
        return f"{path}/{doc_id}"

    def get(self, path: str, doc_id: str) -> dict | None:
        raw = self._c.find_one({"_id": self._key(path, doc_id)})
        return self._out(raw) if raw else None

    def list(self, path, filters=None, order_by=None, desc=False, limit=None) -> list[dict]:
        query: dict[str, Any] = {"_path": path}
        remaining: list[Filter] = []
        for field, op, value in filters or []:
            if op == "==" and value is not None:
                query[field] = value
            elif op == "in":
                query[field] = {"$in": list(value)}
            else:
                remaining.append((field, op, value))
        docs = [self._out(r) for r in self._c.find(query)]
        return apply_query(docs, remaining, order_by, desc, limit)

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict:
        doc_id = doc_id or uuid.uuid4().hex
        stamp = now_iso()
        self._c.insert_one(
            {**data, "_id": self._key(path, doc_id), "_path": path, "_doc_id": doc_id,
             "created_at": stamp, "updated_at": stamp}
        )
        return self.get(path, doc_id)  # type: ignore[return-value]

    def update(self, path: str, doc_id: str, data: dict) -> dict | None:
        res = self._c.update_one({"_id": self._key(path, doc_id)}, {"$set": {**data, "updated_at": now_iso()}})
        return self.get(path, doc_id) if res.matched_count else None

    def set(self, path: str, doc_id: str, data: dict) -> dict:
        existing = self._c.find_one({"_id": self._key(path, doc_id)}, {"created_at": 1})
        created = (existing or {}).get("created_at") or now_iso()
        self._c.replace_one(
            {"_id": self._key(path, doc_id)},
            {**data, "_id": self._key(path, doc_id), "_path": path, "_doc_id": doc_id,
             "created_at": created, "updated_at": now_iso()},
            upsert=True,
        )
        return self.get(path, doc_id)  # type: ignore[return-value]

    def delete(self, path: str, doc_id: str) -> bool:
        return self._c.delete_one({"_id": self._key(path, doc_id)}).deleted_count > 0


# Path helpers --------------------------------------------------------------

def farm_path(farm_id: str, collection: str) -> str:
    return f"farms/{farm_id}/{collection}"
