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

django-admin migrate --noinput
django-admin collectstatic --noinput --clear

uwsgi --ini docker/prod/uwsgi.ini

exec "$@"
