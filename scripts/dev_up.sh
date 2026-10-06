#!/usr/bin/env bash
# Local development without Docker.
#
# Assumes PostgreSQL 16+ and Redis 7+ are already running locally and that the database
# and role from .env exist. Starts the API, a Celery worker, beat and the frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example - set OPENROUTER_API_KEY and PARALLEL_API_KEY."
  cp .env.example .env
  # Local runs talk to localhost, not the Compose service names.
  sed -i.bak 's/^POSTGRES_HOST=postgres/POSTGRES_HOST=localhost/' .env
  sed -i.bak 's|redis://redis:|redis://localhost:|g' .env
  sed -i.bak 's|^S3_ENDPOINT_URL=.*|S3_ENDPOINT_URL=|' .env
  sed -i.bak 's|^S3_ACCESS_KEY=.*|S3_ACCESS_KEY=|' .env
  sed -i.bak 's|^S3_SECRET_KEY=.*|S3_SECRET_KEY=|' .env
  rm -f .env.bak
fi

echo "==> Backend virtual environment"
cd backend
if [[ ! -d .venv ]]; then
  python -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/*/activate 2>/dev/null || source .venv/bin/activate
pip install -q -r requirements-dev.txt

echo "==> Applying the database schema"
cd "$ROOT"
PSQL_ARGS=(-v ON_ERROR_STOP=1)
for file in db/extensions.sql db/schema.sql db/functions.sql db/rls.sql; do
  echo "    $file"
  psql "${PSQL_ARGS[@]}" -f "$file" || {
    echo "    (already applied or requires elevated privileges - continuing)"
  }
done

echo "==> Seeding roles, demo tenant and administrator"
cd backend
python -m scripts.seed

echo "==> Starting services"
uvicorn app.main:app --reload --port 8000 &
API_PID=$!
celery -A app.workers.celery_app.celery_app worker \
  --loglevel=info --queues=default,ingest,ai,index --concurrency=2 &
WORKER_PID=$!
celery -A app.workers.celery_app.celery_app beat --loglevel=info &
BEAT_PID=$!

cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install --no-audit --no-fund
fi
API_INTERNAL_URL=http://localhost:8000 npm run dev &
WEB_PID=$!

trap 'kill $API_PID $WORKER_PID $BEAT_PID $WEB_PID 2>/dev/null || true' EXIT INT TERM

echo
echo "Frontend  http://localhost:3000"
echo "API docs  http://localhost:8000/docs"
echo "Press Ctrl-C to stop."
wait
