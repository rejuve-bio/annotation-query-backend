FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

ARG APP_PORT

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE $APP_PORT

CMD gunicorn -w 16 --bind 0.0.0.0:$APP_PORT run:app
