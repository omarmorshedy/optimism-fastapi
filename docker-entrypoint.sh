#!/bin/sh
# Optimism container entrypoint: run migrations BEFORE routing traffic
# (plan §2 / arc42 §7.5), then start the web server.
set -e

if [ "$AUTO_MIGRATE" = "true" ]; then
    echo "Running database migrations (alembic upgrade head)..."
    alembic upgrade head
fi

exec gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 app.main:app
