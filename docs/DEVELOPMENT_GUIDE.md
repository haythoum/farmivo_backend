# Development guide

## 0. What you need
Python 3.12+, Docker (for local MongoDB), a Firebase project, Android Studio (JDK 17), Xcode 15+ with `xcodegen` (`brew install xcodegen`).

## 1. Firebase (sign-in and push only)
1. Console → create project (the free *Spark* plan is enough; nothing here needs billing).
2. **Authentication → Sign-in method → Email/Password**: enable.
3. **Project settings → Your apps**: add an Android app (`com.farmivo.app`) → download `google-services.json` into `farmivo_android/app/`. Add an iOS app (`com.farmivo.app`) → download `GoogleService-Info.plist` into the Xcode `Farmivo` target. Both files are git-ignored.
4. **Cloud Messaging**: for iOS upload an APNs auth key (Apple Developer account) under Project settings → Cloud Messaging.
5. **Project settings → Service accounts → Generate new private key** → save as `farmivo_backend/serviceAccountKey.json` (git-ignored). The backend uses it to verify tokens and send pushes.

## 2. Backend
```bash
cd farmivo_backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d mongo
cp .env.example .env     # set FARMIVO_FIREBASE_PROJECT_ID; keep the Mongo defaults locally
export GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
uvicorn app.main:app --reload      # http://localhost:8000/docs
pytest                              # no database or Firebase needed
```
Smoke test without an app: sign in through a client to get an ID token, then
`curl -H "Authorization: Bearer $TOKEN" localhost:8000/v1/dashboard`.

### Configuration (`FARMIVO_*` environment variables)
| Variable | Meaning |
|---|---|
| `DB_BACKEND` | `mongo` (default) or `firestore` |
| `MONGO_URI`, `MONGO_DB` | Connection string (local `mongodb://localhost:27017`, Atlas `mongodb+srv://…`) and database name |
| `PUBLIC_BASE_URL` | Public URL of the API; used to build photo URLs |
| `FIREBASE_PROJECT_ID` | Firebase project (token verification, FCM) |
| `CRON_SECRET` | Shared secret for the daily reminder job |
| `CORS_ORIGINS` | Only for browser clients; mobile apps do not need it |
| `FIREBASE_STORAGE_BUCKET` | Only with `DB_BACKEND=firestore` |

### Deploy
Any host that runs the `Dockerfile` (Render, Railway, Fly.io, a VPS, Cloud Run).
1. Create a MongoDB Atlas cluster (free M0 is fine to start), create a database user, allow the host's IP, copy the connection string.
2. Deploy the container with the environment variables above (`PUBLIC_BASE_URL` = the final https URL) and the service-account JSON (as a secret file, `GOOGLE_APPLICATION_CREDENTIALS`).
3. Schedule a daily job (07:00 local) that runs `curl -X POST -H "X-Cron-Secret: $SECRET" https://<host>/v1/internal/reminders/run`. Any scheduler works (host cron, GitHub Actions, cron-job.org, Cloud Scheduler).
4. Put the https URL into both apps' release configuration.

## 3. Android
```bash
cd farmivo_android
# put google-services.json in app/
# app/build.gradle: debug API_BASE_URL = http://10.0.2.2:8000/v1/ (emulator -> your computer), release = your https URL
gradle wrapper    # once, creates ./gradlew
./gradlew assembleDebug   # or open in Android Studio and Run
```

## 4. iOS
```bash
cd farmivo_ios
xcodegen generate && open Farmivo.xcodeproj
# add GoogleService-Info.plist to the Farmivo target
# Config/Debug.xcconfig API_BASE_URL = http://localhost:8000/v1/ (simulator); Release = your https URL
```
Set your Team in Signing & Capabilities; add **Push Notifications** capability (entitlement file already present). Push needs a real device.

## 5. Everyday tasks
| Task | Where |
|---|---|
| Add a field to a record (e.g. vaccination "dose") | Backend: `schemas.py` model. Apps: one `Field` line in the resource registry. Update `docs/API.md`. |
| Add a new record type | Backend: models in `schemas.py` + `build_crud_router(...)` + `include_router` in `main.py`. Apps: add a `Resource` entry; add it to a tab list. |
| Change reminder timing | `reminder_bucket()` in `services/reminders.py` |
| Add a species gestation | `GESTATION_DAYS` in `utils.py` |
| Switch database | `FARMIVO_DB_BACKEND` |
| Back up data | Atlas backups, or `mongodump --uri "$FARMIVO_MONGO_URI" --db farmivo` |

## 6. Testing
- Backend: `pytest` — API behaviour (auth, CRUD, reminders, breeding/births, finance, photos, reports) plus repository tests. The Mongo repository test uses `mongomock`.
- Android / iOS: iOS has `FarmivoTests` (JSON decoding, formatting, error parsing). Android has no tests yet (see STATUS.md).
- Manual end-to-end checklist: register → add animal with photo → add vaccination with next due date → see the reminder → call the cron endpoint → receive the push → record a mating → record the birth → check the offspring exist and the dashboard changed → export a CSV report.

## 7. Troubleshooting
| Symptom | Likely cause |
|---|---|
| App shows "Firebase is not configured" | `google-services.json` / `GoogleService-Info.plist` missing |
| Every call returns 401 | Backend service-account/project id mismatch with the app's Firebase project |
| Android cannot reach backend | Using `localhost` instead of `10.0.2.2` on the emulator; real device needs your LAN IP or a public URL |
| Photos upload but do not display | `PUBLIC_BASE_URL` wrong (the URL stored in the animal is built from it) |
| No push on iOS | APNs key not uploaded to Firebase, simulator used, or capability missing |
| Reminders never notify | Daily job not scheduled, wrong `X-Cron-Secret`, or the device token was never registered |
