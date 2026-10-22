#!/bin/sh
set -e

# Only the web container runs migrations (set RUN_MIGRATIONS=1 there), never workers/beat,
# so concurrent containers cannot race each other on schema changes.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Applying database migrations..."
  python manage.py migrate --noinput
fi

exec "$@"
