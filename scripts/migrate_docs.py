"""Move records from the old single `docs` collection into one collection per type.

    python -m scripts.migrate_docs           # copy, then report
    python -m scripts.migrate_docs --drop    # also drop the old `docs` collection afterwards

Safe to run more than once: records already copied are skipped.
"""
from __future__ import annotations

import argparse

from app.config import get_settings
from app.deps import _mongo_db
from app.repository import MongoRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--drop", action="store_true", help="drop the old docs collection after copying")
    args = parser.parse_args()

    from flask import Flask

    with Flask(__name__).app_context():
        db = _mongo_db()
    prefix = get_settings().mongo_prefix
    old = db[f"{prefix}docs"]
    repo = MongoRepository(db, prefix)
    copied = skipped = 0
    for raw in old.find():
        path, doc_id = raw["_path"], raw["_doc_id"]
        data = {k: v for k, v in raw.items() if k not in ("_id", "_path", "_doc_id")}
        if repo.get(path, doc_id):
            skipped += 1
            continue
        collection, parent = repo._locate(path)
        collection.insert_one({**data, **parent, "_id": doc_id})
        copied += 1
    print(f"copied {copied}, already there {skipped}")
    if args.drop and copied + skipped == old.count_documents({}):
        old.drop()
        print("old docs collection dropped")


if __name__ == "__main__":
    main()
