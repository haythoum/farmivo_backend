# Farmivo backend
**Smart Farming. Better Living.**

Flask (served by gunicorn under supervisor) + MongoDB (data) + photos in GridFS or a MinIO bucket + Firebase (sign-in and push notifications only; both free). Firestore remains available with `FARMIVO_DB_BACKEND=firestore`. The mobile apps ([Android](https://github.com/haythoum/farmivo_android), [iOS](https://github.com/haythoum/farmivo_ios)) sign in with Firebase Auth and call this API with the ID token.

API contract: [docs/API.md](docs/API.md). Full documentation: [docs/](docs/README.md).

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d mongo  # local MongoDB (or set FARMIVO_MONGO_HOST/USER/PASSWORD for your server)
cp .env.example .env        # set the Firebase project id and Mongo URI
export GOOGLE_APPLICATION_CREDENTIALS=./serviceAccountKey.json
flask --app app.main run --debug --port 8000
pytest                      # runs against an in-memory repository, no Firebase needed
```

## Deploy on a server (supervisor + gunicorn)
```bash
sudo cp deploy/supervisor/farmivo.conf /etc/supervisor/conf.d/farmivo.conf
sudo supervisorctl reread && sudo supervisorctl update && sudo supervisorctl status farmivo
```
Step by step (dedicated Mongo user, MinIO bucket and access key, nginx, daily reminder cron): [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md#deploy-on-your-own-server-supervisor). A `Dockerfile` (gunicorn) is also provided for container hosts. `firestore.rules` is only relevant if you choose the Firestore backend.
