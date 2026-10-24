#!/bin/sh
set -e
python manage.py migrate --noinput
# ASGI server: serves normal pages and the live-update WebSocket.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --workers 2
