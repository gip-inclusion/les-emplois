#!/bin/sh
set -e

# ------ Specific to Clever Cloud ------
# If $POSTGRESQL_ADDON_* is set, replace POSTGRES_* by its value.
# Otherwise, keep our default configuration.
POSTGRES_HOST=${POSTGRESQL_ADDON_HOST:-$POSTGRES_HOST}
POSTGRES_PORT=${POSTGRESQL_ADDON_PORT:-$POSTGRES_PORT}

while ! pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

# # https://github.com/docker/compose/issues/1926#issuecomment-422351028
# trap : TERM INT
# tail -f /dev/null & wait

django-admin migrate
django-admin runserver_plus 0.0.0.0:8000

exec "$@"
