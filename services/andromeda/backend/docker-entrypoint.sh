#!/bin/sh
set -eu

if [ -z "${ANDROMEDA_DATABASE_URL:-}" ]; then
  echo "ANDROMEDA_DATABASE_URL must be set explicitly for the runtime image" >&2
  exit 64
fi

case "$ANDROMEDA_DATABASE_URL" in
  postgresql://*|postgresql+*) ;;
  *)
    echo "ANDROMEDA_DATABASE_URL must be a PostgreSQL URL in the runtime image" >&2
    exit 64
    ;;
esac

python /app/scripts/preflight.py --profile bmstu --profile hse
python -m alembic -c /app/alembic.ini upgrade head
exec uvicorn andromeda.api.main:app --host 0.0.0.0 --port "${PORT:-8020}"
