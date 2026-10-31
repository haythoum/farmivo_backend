FROM python:3.12-slim
WORKDIR /srv/farmivo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD exec gunicorn --bind 0.0.0.0:8000 app.main:app
