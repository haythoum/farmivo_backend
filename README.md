# Farmivo backend
**Smart Farming. Better Living.**

FastAPI + Firebase (Auth, Firestore, Storage, Cloud Messaging). The mobile apps ([Android](https://github.com/haythoum/farmivo_android), [iOS](https://github.com/haythoum/farmivo_ios)) sign in with Firebase Auth and call this API with the ID token.

API contract: [docs/API.md](docs/API.md) (Swagger at `/docs` when running).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # fill in the Firebase project
export GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
uvicorn app.main:app --reload
pytest                      # runs against an in-memory repository, no Firebase needed
```

## Deploy (Cloud Run)
```bash
gcloud run deploy farmivo-api --source . --region <region> \
  --set-env-vars FARMIVO_FIREBASE_PROJECT_ID=<id>,FARMIVO_FIREBASE_STORAGE_BUCKET=<bucket>,FARMIVO_CRON_SECRET=<secret>
```
Create a Cloud Scheduler job (daily, e.g. 07:00) that POSTs `https://<host>/v1/internal/reminders/run` with header `X-Cron-Secret: <secret>`. It sends the 7-day / 1-day / due-today / overdue push notifications.

Deploy `firestore.rules` (denies all direct client access; data is only reachable through this API).
