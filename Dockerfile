FROM python:3.12-slim
WORKDIR /srv/farmivo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080
CMD exec gunicorn --workers 2 --bind 0.0.0.0:${PORT} --access-logfile - app.main:app
