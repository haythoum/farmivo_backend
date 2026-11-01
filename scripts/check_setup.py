"""Check the server setup step by step and say exactly what is wrong.

    python -m scripts.check_setup

Reads the same .env as the API. Prints one line per check; stops at the first failure with the fix.
Never prints passwords.
"""
from __future__ import annotations

import sys

from app.config import ENV_FILE, get_settings


def ok(msg: str) -> None:
    print(f"OK    {msg}")


def fail(msg: str, fix: str) -> None:
    print(f"FAIL  {msg}\n      Fix: {fix}")
    sys.exit(1)


def check_settings():
    if not ENV_FILE.exists():
        fail(f"settings file {ENV_FILE} not found", "put .env next to the app/ folder")
    settings = get_settings()
    ok(f"settings file {ENV_FILE}")
    if settings.mongo_uri:
        ok("MongoDB from FARMIVO_MONGO_URI (the HOST/USER/PASSWORD fields are ignored)")
    else:
        ok(f"MongoDB {settings.mongo_host}:{settings.mongo_port}, user {settings.mongo_user or '(none)'}, "
           f"auth database {settings.mongo_auth_db or settings.mongo_db}, data database {settings.mongo_db}")
    return settings


def check_mongo(settings) -> None:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import OperationFailure, PyMongoError

    ok(f"PyMongo {pymongo.version}")
    client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    try:
        info = client.server_info()
    except OperationFailure as exc:
        if exc.code == 18:
            fail("MongoDB login refused (Authentication failed)",
                 "wrong user/password, or FARMIVO_MONGO_AUTH_DB is not the database where the user was created")
        fail(f"MongoDB refused: {exc}", "see the message above")
    except PyMongoError as exc:
        fail(f"cannot use MongoDB: {exc}",
             "wire version error: pip install 'pymongo>=4.8,<4.11'; connection error: check host/port")
    ok(f"MongoDB server {info.get('version')}, logged in")

    db = client[settings.mongo_db]
    try:
        db["docs"].create_index("_path")
        db["setup_check"].insert_one({"check": True})
        db["setup_check"].drop()
    except OperationFailure as exc:
        if exc.code == 13:
            fail(f"user '{settings.mongo_user}' may not write to database '{settings.mongo_db}'",
                 f"give that user readWrite on {settings.mongo_db}, or create a user in it: "
                 f"use {settings.mongo_db}; db.createUser({{user:'farmivo_app', pwd:'...', "
                 f"roles:[{{role:'readWrite', db:'{settings.mongo_db}'}}]}}) and set FARMIVO_MONGO_USER/"
                 f"PASSWORD and FARMIVO_MONGO_AUTH_DB={settings.mongo_db}")
        fail(f"MongoDB write refused: {exc}", "see the message above")
    ok(f"can read and write database '{settings.mongo_db}'")


def check_firebase(settings) -> None:
    import os
    from pathlib import Path

    if not settings.firebase_project_id:
        fail("FARMIVO_FIREBASE_PROJECT_ID is empty", "set FARMIVO_FIREBASE_PROJECT_ID=farmivo-4d932")
    key = settings.firebase_credentials or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key:
        fail("no Firebase service-account key configured", "set FARMIVO_FIREBASE_CREDENTIALS=/full/path/serviceAccountKey.json")
    path = Path(key) if Path(key).is_absolute() else ENV_FILE.parent / key
    if not path.is_file():
        fail(f"Firebase key not found at {path}", "fix the path in FARMIVO_FIREBASE_CREDENTIALS")
    import json

    try:
        project = json.loads(path.read_text()).get("project_id")
    except (OSError, ValueError) as exc:
        fail(f"cannot read the Firebase key: {exc}", "check the file permissions (chmod 600, owned by the app user)")
    if project != settings.firebase_project_id:
        fail(f"Firebase key is for project '{project}', settings say '{settings.firebase_project_id}'",
             "download the key from the farmivo-4d932 project")
    ok(f"Firebase key for project {project}")


if __name__ == "__main__":
    s = check_settings()
    check_mongo(s)
    check_firebase(s)
    print("All checks passed. Restart the API: sudo supervisorctl restart farmivo")
