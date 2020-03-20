#!/bin/sh
set -e

while ! pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

# # https://github.com/docker/compose/issues/1926#issuecomment-422351028
# trap : TERM INT
# tail -f /dev/null & wait

django-admin migrate
# django-admin runserver_plus 0.0.0.0:8000
# PEAMU redirect_uri works with port 8080 but not 8000
# Disable annoying debug PIN code in local development.
# Of course we keep it in production for security!
django-admin runserver_plus 0.0.0.0:8080 --nopin
# KO, frontend does not respond
# django-admin runserver_plus localhost:8000

exec "$@"
