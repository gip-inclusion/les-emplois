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

django-admin migrate

# --nopin disables for you the annoying PIN security prompt on the web
# debugger. For local dev only of course!
# --keep-meta-shutdown is set to avoid this issue : https://github.com/django-extensions/django-extensions/issues/1715
# This option should be removed when the package Werkzeug is updated with the fix.
django-admin runserver_plus --keep-meta-shutdown 0.0.0.0:8000 --nopin

exec "$@"
