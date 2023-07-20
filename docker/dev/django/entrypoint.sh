#!/bin/sh
set -e

while ! pg_isready; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

# # https://github.com/docker/compose/issues/1926#issuecomment-422351028
# trap : TERM INT
# tail -f /dev/null & wait

./manage.py migrate

./manage.py runserver 0.0.0.0:8000

exec "$@"
