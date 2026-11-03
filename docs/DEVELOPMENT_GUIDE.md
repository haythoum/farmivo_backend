# Development guide

## 0. What you need
Python 3.12+, Docker (for local MongoDB), a Firebase project, Android Studio (JDK 17), Xcode 15+ with `xcodegen` (`brew install xcodegen`).

## App identifiers
Android package/applicationId and iOS bundle id are both **`com.quadralens.farmivo`**. Android sources live in `app/src/main/java/com/quadralens/farmivo/`. Register exactly this id in Firebase and in Google Play / App Store Connect; it cannot be changed after publishing.

## 1. Firebase (sign-in and push only)
1. Console → create project (the free *Spark* plan is enough; nothing here needs billing).
2. **Authentication → Sign-in method → Email/Password**: enable.
3. **Project settings → Your apps**: the Firebase project is **`farmivo-4d932`** with an Android app and an iOS app, both `com.quadralens.farmivo`. Their config files are already committed in the app repos (`farmivo_android/app/google-services.json`, `farmivo_ios/Farmivo/Resources/GoogleService-Info.plist`); the repos are private. These contain client identifiers, not secrets, but restrict the API keys (Google Cloud Console → APIs & Services → Credentials) to the app ids. To use another Firebase project, replace both files and `FARMIVO_FIREBASE_PROJECT_ID`.
4. **Cloud Messaging**: for iOS upload an APNs auth key (Apple Developer account) under Project settings → Cloud Messaging.
5. **Project settings → Service accounts → Generate new private key** → save as `farmivo_backend/serviceAccountKey.json` (git-ignored). The backend uses it to verify tokens and send pushes. **This one is a real secret: never commit it or paste it in chat.** It has not been provided yet, so the backend cannot verify tokens until you add it.

## 2. Backend
```bash
cd farmivo_backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d mongo
cp .env.example .env     # FARMIVO_FIREBASE_PROJECT_ID is `farmivo-4d932` in the example; keep the Mongo defaults locally
export GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
flask --app app.main run --debug --port 8000   # http://localhost:8000/healthz
pytest                              # no database or Firebase needed
```
Smoke test without an app: sign in through a client to get an ID token, then
`curl -H "Authorization: Bearer $TOKEN" localhost:8000/v1/dashboard`.

### Configuration (`FARMIVO_*` environment variables)
| Variable | Meaning |
|---|---|
| `DB_BACKEND` | `mongo` (default) or `firestore` |
| `MONGO_HOST`, `MONGO_PORT`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_AUTH_DB`, `MONGO_DB` | MongoDB server, login and database. The password needs no escaping. `MONGO_AUTH_DB` is the database where the user was created (empty = `MONGO_DB`). On startup the log prints `MongoDB: <host>, database <db>, user <user>` or says what is wrong. |
| MongoDB version | Works with MongoDB 3.6 and newer. `requirements.txt` pins PyMongo below 4.11 because newer PyMongo refuses servers older than 4.0/4.4 (`reports wire version 6`). When the server is upgraded to MongoDB 4.4+, the pin can be lifted. |
| `MONGO_URI` (optional) | One connection string instead of the fields (Atlas: `mongodb+srv://…`). Overrides them. Special characters in the password must be URL-encoded (`@` → `%40`, `:` → `%3A`, `/` → `%2F`, `#` → `%23`). |
| `PHOTO_STORE` | `gridfs` (default, photos inside the Mongo database) or `minio` |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE` | Only with `PHOTO_STORE=minio`. Bucket default `farmivo-photos` (created if missing); `MINIO_SECURE=true` for https |
| `PUBLIC_BASE_URL` | Public URL of the API; used to build photo URLs |
| `FIREBASE_PROJECT_ID` | Firebase project (token verification, FCM) |
| `CRON_SECRET` | Shared secret for the daily reminder job |
| `MAILJET_API_KEY`, `MAILJET_API_SECRET` (no `FARMIVO_` prefix), `MAIL_FROM_EMAIL`, `MAIL_FROM_NAME` | Mailjet account and sender for the 6-digit sign-up code. Empty key: the code is written to the server log instead (see "Email (sign-up code)" below) |
| `CODE_SECRET` | Key for hashing the codes (any long random string); empty = `CRON_SECRET` |
| `CORS_ORIGINS` | Only for browser clients; mobile apps do not need it |
| `TIMEZONE` | Time zone of the farms (default `Africa/Tunis`): decides what "today" is for reminder buckets, overdue checks, default dates and reports, whatever zone the server clock uses |
| `FIREBASE_STORAGE_BUCKET` | Only with `DB_BACKEND=firestore` |

### Deploy on your own server (supervisor)
For a server that already runs MongoDB (and optionally MinIO). The API runs as a gunicorn process managed by supervisor, behind nginx.

1. **Code and virtualenv**
   ```bash
   sudo mkdir -p /srv/farmivo /var/log/farmivo && sudo chown www-data: /var/log/farmivo
   git clone -b feature/initial-api https://github.com/haythoum/farmivo_backend.git /srv/farmivo
   cd /srv/farmivo && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
2. **Database: a new Mongo database with its own user.** Do not reuse another app's database or login. In `mongosh` as an admin:
   ```js
   use farmivo
   db.createUser({ user: "farmivo_app", pwd: "<strong password>", roles: [{ role: "readWrite", db: "farmivo" }] })
   ```
   The database itself is created on the first write. Connection string: `mongodb://farmivo_app:<password>@<host>:27017/farmivo?authSource=farmivo` (URL-encode special characters). If Mongo and the API run on the same server, use `localhost`.
3. **Photos: pick one.**
   - `FARMIVO_PHOTO_STORE=gridfs` (default): nothing to set up; photos live in the `farmivo` database.
   - `FARMIVO_PHOTO_STORE=minio`: create a **new bucket** `farmivo-photos` (the API also creates it if the key may). In the MinIO console create a **dedicated access key** (policy limited to that bucket, e.g. `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`, `s3:CreateBucket` on `farmivo-photos`) and put it in `.env`. Keep the bucket private: the API streams images through `/v1/photos/<id>`.
4. **Settings:** `cp .env.example .env`, fill in `FARMIVO_MONGO_HOST`, `FARMIVO_MONGO_USER`, `FARMIVO_MONGO_PASSWORD` (and `FARMIVO_MONGO_AUTH_DB` if the user lives in another database), `FARMIVO_PUBLIC_BASE_URL` (final https URL), `FARMIVO_CRON_SECRET`, MinIO values if used. Put the Firebase service-account key next to `.env` as `serviceAccountKey.json` (`chmod 600`, owned by the user supervisor runs the app as) and set `FARMIVO_FIREBASE_CREDENTIALS=serviceAccountKey.json`. **Without the key every token is rejected with 401.** Never commit `.env` or the key.
5. **supervisor**
   ```bash
   sudo cp deploy/supervisor/farmivo.conf /etc/supervisor/conf.d/farmivo.conf
   sudo supervisorctl reread && sudo supervisorctl update
   sudo supervisorctl status farmivo        # RUNNING
   curl localhost:8000/healthz               # {"status":"ok"}
   ```
   After a code update: `git pull && .venv/bin/pip install -r requirements.txt && sudo supervisorctl restart farmivo`. Logs: `/var/log/farmivo/`.
6. **nginx + TLS** (`deploy/nginx/farmivo.conf`, then `certbot --nginx`): the apps need https in production.
7. **Daily reminders:** add a cron entry (07:00 local): `0 7 * * * curl -fsS -X POST -H "X-Cron-Secret: <secret>" https://<host>/v1/internal/reminders/run`.
8. **Firewall:** MongoDB (27017) and MinIO (9000/9001) should only accept connections from the API server itself (or a private network), not from the internet. Expose only 80/443.
9. Put the https URL into both apps' release configuration.

The `Dockerfile` (`gunicorn --bind 0.0.0.0:8000 app.main:app`) is an alternative for container hosts.

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
| Add a new record type | Backend: models in `schemas.py` + `build_crud_blueprint(...)` registered in the module's blueprint (and the module in `main.py`). Apps: add a `Resource` entry; add it to a tab list. |
| Change reminder timing | `reminder_bucket()` in `services/reminders.py` |
| Add a species gestation | `GESTATION_DAYS` in `utils.py` |
| Switch database | `FARMIVO_DB_BACKEND` |
| Back up data | Atlas backups, or `mongodump --host <host> -u <user> -p --authenticationDatabase <auth db> --db farmivo` |

## 6. Testing
- Backend: `pytest` — API behaviour (auth, CRUD, reminders, breeding/births, finance, photos, reports) plus repository tests. The Mongo repository test uses `mongomock`.
- Android / iOS: iOS has `FarmivoTests` (JSON decoding, formatting, error parsing). Android has no tests yet (see STATUS.md).
- Manual end-to-end checklist: register → add animal with photo → add vaccination with next due date → see the reminder → call the cron endpoint → receive the push → record a mating → record the birth → check the offspring exist and the dashboard changed → export a CSV report.

## 7. Troubleshooting
| Symptom | Likely cause |
|---|---|
| App shows "Firebase is not configured" | `google-services.json` / `GoogleService-Info.plist` missing or the bundle id does not match |
| Every call returns 401 | Missing service-account key (`FARMIVO_FIREBASE_CREDENTIALS`), or key/project id from another Firebase project. The log line `Rejected Firebase token:` says which |
| Android cannot reach backend | Using `localhost` instead of `10.0.2.2` on the emulator; real device needs your LAN IP or a public URL |
| Photos upload but do not display | `PUBLIC_BASE_URL` wrong (the URL stored in the animal is built from it) |
| No push on iOS | APNs key not uploaded to Firebase, simulator used, or capability missing |
| Reminders never notify | Daily job not scheduled, wrong `X-Cron-Secret`, or the device token was never registered |

## Demo data

A new database is empty, so the apps show zeros and empty lists until someone adds records. To fill your farm with sample animals, vaccinations, a breeding, weights, milk, feeding and finance entries:

```bash
cd /srv/farmivo && source .venv/bin/activate
python -m scripts.seed_demo --uid <Firebase user id>
```

The user id is in the Firebase console under Authentication > Users ("User UID"). Sign in to the app once first so the account exists. The script uses the real database from `.env`, goes through the normal API code, and writes nothing if the farm already has animals. Add `--memory` for a dry run.

## "Invalid or expired token" (401) with a valid sign-in

The server logs the real reason every time it rejects a token: `tail -n 30 /var/log/farmivo/farmivo.err.log` and look for `Rejected Firebase token:`.

| Log message contains | Cause | Fix |
|---|---|---|
| `DefaultCredentialsError` / `credentials were not found` / `No Firebase service-account key` | The server has no service-account key | Set `FARMIVO_FIREBASE_CREDENTIALS=serviceAccountKey.json` in `.env` (file next to `.env`), restart |
| `incorrect "aud"` / `audience` | The token belongs to another Firebase project than the server expects | Set `FARMIVO_FIREBASE_PROJECT_ID=farmivo-4d932` in `/srv/farmivo/.env` and make sure the service-account key (if any) and the app's `google-services.json` are from that same project; then `supervisorctl restart farmivo` |
| `Token used too early` / `too late` | The server clock is wrong | Fix the time: `timedatectl set-ntp true` |
| `expired` | The token is older than 1 hour | Get a fresh one (sign in again) |
| `Could not verify token signature` / certificate or connection errors | The server cannot reach Google to fetch the signing keys | Allow outbound HTTPS from the server |
| `Firebase ID token has incorrect "iss"` | Wrong project, same as `aud` | Same fix |

Check what the server loaded: `grep FIREBASE /srv/farmivo/.env` and, for the key's project, `grep project_id /srv/farmivo/serviceAccountKey.json`. A key copied from another project (for example SOS Khedma) is a common cause.

## Email (sign-up code)

New accounts confirm their email with a 6-digit code before they can create or join a farm (flow: [ROLES_AND_MEMBERS.md](ROLES_AND_MEMBERS.md#email-verification-code)).

Emails are sent through **Mailjet** (Send API v3.1, package `mailjet-rest`).

**Testing without email:** leave `MAILJET_API_KEY` empty. The code is then written to the server log:
```bash
grep "verification code for" /var/log/farmivo.err.log | tail -1
```

**Sending real emails:** add to `.env`:
```
MAILJET_API_KEY=<Mailjet > Account settings > API keys: API key>
MAILJET_API_SECRET=<secret key>
FARMIVO_MAIL_FROM_EMAIL=contact@quadralens.tn
FARMIVO_MAIL_FROM_NAME=Farmivo
FARMIVO_CODE_SECRET=<openssl rand -hex 24>
```
Then `pip install -r requirements.txt` (installs `mailjet-rest`), `python -m scripts.check_setup` (checks the key and that the sender is validated, sends nothing) and `sudo supervisorctl restart farmivo`.

The sender address must be validated in Mailjet (Senders & Domains). For best delivery, validate the whole domain and add Mailjet's SPF and DKIM records at the domain host.

| Error in the app | Cause | Fix |
|---|---|---|
| "We could not send the email. Try again later" (`502 email_failed`) | Mailjet refused (bad key, sender not validated, quota) or could not be reached; the log has `MailError` with Mailjet's answer | Run `scripts.check_setup` |
| "Please wait N seconds" | A code was sent less than 60 s ago | Wait |
| "Too many codes requested" | 5 codes in the last hour | Wait an hour |

