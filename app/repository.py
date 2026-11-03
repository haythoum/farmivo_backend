"""Storage abstraction.

Records are addressed by slash-separated paths such as ``farms/{farm_id}/animals`` plus an id.
The ``Repository`` protocol has three implementations:

* ``MongoRepository``     - production (MongoDB / Atlas). Default.
* ``FirestoreRepository`` - production alternative (Firebase).
* ``InMemoryRepository``  - tests and local experiments (no Firebase needed).

Only equality (and, for MongoDB, ``in``) filters are pushed down to the database. Range
filters, ordering and limits are applied in Python (``apply_query``). A single farm holds at most a few thousand documents per
collection, and this keeps the project free of composite-index management.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

Filter = tuple[str, str, Any]  # (field, op, value); op in ==, !=, <, <=, >, >=, in


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision); used for created_at/updated_at."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _matches(doc: dict, flt: Filter) -> bool:
    """True if one document satisfies one (field, op, value) filter."""
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
    """Filter, sort (missing values last) and limit a list of documents in Python."""
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
    """Storage interface used by all routers: records are addressed by a path and an id."""

    def get(self, path: str, doc_id: str) -> dict | None:
        """Return one record (with "id") or None."""
        ...

    def list(
        self,
        path: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        """Return the records under a path matching all filters, optionally ordered and limited."""
        ...

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict:
        """Insert a record (new id unless given), stamp created_at/updated_at, return it."""
        ...

    def update(self, path: str, doc_id: str, data: dict) -> dict | None:
        """Merge fields into a record and return it, or None if it does not exist."""
        ...

    def set(self, path: str, doc_id: str, data: dict) -> dict:
        """Create or replace a record with a known id (keeps created_at), return it."""
        ...

    def delete(self, path: str, doc_id: str) -> bool:
        """Delete a record; True if it existed."""
        ...

    def update_where(self, path: str, doc_id: str, expected: dict, data: dict) -> dict | None:
        """Merge ``data`` only if the record still has the ``expected`` field values (compare-and-set).
        Returns the updated record, or None if it is missing or changed meanwhile. Used where two requests
        must not both succeed (approving the same request, recording the same birth)."""
        ...

    def group_list(self, name: str, filters: list[Filter] | None = None) -> list[dict]:
        """Records of every sub-collection called ``name`` (e.g. all farms' ``members``) matching the filters.
        Each record also carries ``parent_id``: the id of the record the collection belongs to (the farm)."""
        ...


class InMemoryRepository:
    """Dictionary-backed repository for tests and the demo seeder's dry run."""
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

    def update_where(self, path: str, doc_id: str, expected: dict, data: dict) -> dict | None:
        doc = self._col(path).get(doc_id)
        if doc is None or any(doc.get(k) != v for k, v in expected.items()):
            return None
        return self.update(path, doc_id, data)

    def group_list(self, name: str, filters: list[Filter] | None = None) -> list[dict]:
        docs = []
        for path, col in self._data.items():
            parts = path.split("/")
            if len(parts) >= 3 and parts[-1] == name:
                docs += [{**copy.deepcopy(d), "id": i, "parent_id": parts[-2]} for i, d in col.items()]
        return apply_query(docs, filters)


class FirestoreRepository:
    """Repository on Google Firestore (alternative backend; equality filters run in Firestore)."""
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

    def update_where(self, path: str, doc_id: str, expected: dict, data: dict) -> dict | None:
        from google.cloud import firestore

        ref = self._db.collection(path).document(doc_id)

        @firestore.transactional
        def run(transaction) -> bool:
            snap = ref.get(transaction=transaction)
            current = snap.to_dict() if snap.exists else None
            if current is None or any(current.get(k) != v for k, v in expected.items()):
                return False
            transaction.update(ref, {**data, "updated_at": now_iso()})
            return True

        return self.get(path, doc_id) if run(self._db.transaction()) else None

    def group_list(self, name: str, filters: list[Filter] | None = None) -> list[dict]:
        docs = [{**self._to_dict(s), "parent_id": s.reference.parent.parent.id}
                for s in self._db.collection_group(name).stream()]
        return apply_query(docs, filters)


class MongoRepository:
    """One MongoDB collection per record type, named after the last part of the path.

    ``farms/<farm_id>/animals`` -> collection ``animals`` with a ``farm_id`` field,
    ``users/<uid>/devices`` -> collection ``devices`` with a ``user_id`` field,
    ``farms`` / ``users`` -> collections ``farms`` / ``users``. The record id is the Mongo ``_id``.
    So in the shell: ``db.animals.find({farm_id: "..."})``.
    """

    def __init__(self, db: Any, prefix: str = "") -> None:
        self._db = db
        self._prefix = prefix
        self._indexed: set[str] = set()

    def _locate(self, path: str) -> tuple[Any, dict]:
        """Collection for a path, plus the parent fields every record in it carries (e.g. farm_id)."""
        parts = path.split("/")
        parent = {f"{parts[i].rstrip('s')}_id": parts[i + 1] for i in range(0, len(parts) - 1, 2)}
        name = self._prefix + parts[-1]
        collection = self._db[name]
        if parent and name not in self._indexed:
            collection.create_index([(key, 1) for key in parent])
            self._indexed.add(name)
        return collection, parent

    @staticmethod
    def _out(raw: dict, parent: dict) -> dict:
        doc = {k: v for k, v in raw.items() if k != "_id" and k not in parent}
        doc["id"] = raw["_id"]
        return doc

    def get(self, path: str, doc_id: str) -> dict | None:
        collection, parent = self._locate(path)
        raw = collection.find_one({"_id": doc_id, **parent})
        return self._out(raw, parent) if raw else None

    def list(self, path, filters=None, order_by=None, desc=False, limit=None) -> list[dict]:
        collection, parent = self._locate(path)
        query: dict[str, Any] = dict(parent)
        remaining: list[Filter] = []
        for field, op, value in filters or []:
            if op == "==" and value is not None and field not in parent:
                query[field] = value
            elif op == "in":
                query[field] = {"$in": list(value)}
            else:
                remaining.append((field, op, value))
        docs = [self._out(r, parent) for r in collection.find(query)]
        return apply_query(docs, remaining, order_by, desc, limit)

    def create(self, path: str, data: dict, doc_id: str | None = None) -> dict:
        collection, parent = self._locate(path)
        doc_id = doc_id or uuid.uuid4().hex
        stamp = now_iso()
        collection.insert_one({**data, **parent, "_id": doc_id, "created_at": stamp, "updated_at": stamp})
        return self.get(path, doc_id)  # type: ignore[return-value]

    def update(self, path: str, doc_id: str, data: dict) -> dict | None:
        collection, parent = self._locate(path)
        res = collection.update_one({"_id": doc_id, **parent}, {"$set": {**data, "updated_at": now_iso()}})
        return self.get(path, doc_id) if res.matched_count else None

    def set(self, path: str, doc_id: str, data: dict) -> dict:
        collection, parent = self._locate(path)
        existing = collection.find_one({"_id": doc_id}, {"created_at": 1})
        created = (existing or {}).get("created_at") or now_iso()
        collection.replace_one(
            {"_id": doc_id},
            {**data, **parent, "_id": doc_id, "created_at": created, "updated_at": now_iso()},
            upsert=True,
        )
        return self.get(path, doc_id)  # type: ignore[return-value]

    def delete(self, path: str, doc_id: str) -> bool:
        collection, parent = self._locate(path)
        return collection.delete_one({"_id": doc_id, **parent}).deleted_count > 0

    def update_where(self, path: str, doc_id: str, expected: dict, data: dict) -> dict | None:
        collection, parent = self._locate(path)
        # One atomic update_one: the filter includes the expected values (works on MongoDB 3.6).
        query = {**expected, **parent, "_id": doc_id}
        res = collection.update_one(query, {"$set": {**data, "updated_at": now_iso()}})
        return self.get(path, doc_id) if res.matched_count else None

    def group_list(self, name: str, filters: list[Filter] | None = None) -> list[dict]:
        query = {f: v for f, op, v in filters or [] if op == "=="}
        rest = [flt for flt in filters or [] if flt[1] != "=="]
        docs = []
        for raw in self._db[self._prefix + name].find(query):
            # farm sub-collections carry farm_id, user sub-collections user_id (see _locate)
            parent_key = "farm_id" if "farm_id" in raw else ("user_id" if "user_id" in raw else None)
            doc = {k: v for k, v in raw.items() if k not in ("_id", parent_key)}
            doc["id"], doc["parent_id"] = raw["_id"], raw.get(parent_key) if parent_key else None
            docs.append(doc)
        return apply_query(docs, rest)


# Path helpers --------------------------------------------------------------

def farm_path(farm_id: str, collection: str) -> str:
    """Path of a farm's sub-collection, e.g. farms/<farm_id>/animals."""
    return f"farms/{farm_id}/{collection}"
