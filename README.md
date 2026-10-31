# Farmivo backend
**Smart Farming. Better Living.**

FastAPI + MongoDB (data and animal photos via GridFS) + Firebase (sign-in and push notifications only; both free). Firestore remains available with `FARMIVO_DB_BACKEND=firestore`. The mobile apps ([Android](https://github.com/haythoum/farmivo_android), [iOS](https://github.com/haythoum/farmivo_ios)) sign in with Firebase Auth and call this API with the ID token.

API contract: [docs/API.md](docs/API.md) (Swagger at `/docs` when running).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d mongo  # local MongoDB (or use a free MongoDB Atlas cluster)
cp .env.example .env        # set the Firebase project id and Mongo URI
export GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
uvicorn app.main:app --reload
pytest                      # runs against an in-memory repository, no Firebase needed
```

## Deploy (Cloud Run)
```bash
gcloud run deploy farmivo-api --source . --region <region> \
  --set-env-vars FARMIVO_MONGO_URI=<atlas-uri>,FARMIVO_PUBLIC_BASE_URL=https://<host>,FARMIVO_FIREBASE_PROJECT_ID=<id>,FARMIVO_CRON_SECRET=<secret>
```
Create a Cloud Scheduler job (daily, e.g. 07:00) that POSTs `https://<host>/v1/internal/reminders/run` with header `X-Cron-Secret: <secret>`. It sends the 7-day / 1-day / due-today / overdue push notifications.

Any host that runs a Docker container works (Render, Railway, Fly.io, a VPS); Cloud Run is only an example. `firestore.rules` is only relevant if you choose the Firestore backend.
