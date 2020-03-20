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

# 1) about 0.0.0.0 vs localhost
#
# PEAMU works only with localhost URL and not 0.0.0.0
# Thus we would like to use localhost here instead of 0.0.0.0
# so that the correct URL appears right away in the
# development server output. However I could not make it work. :-(
# So you just have to know that you should access your local dev
# by localhost:8080 and not by 0.0.0.0:8080 like the console says.
#
# 2) about --nopin
#
# Disable for you the annoying PIN security prompt on the web
# debugger. For local dev only of course!
django-admin runserver_plus 0.0.0.0:8080 --nopin

exec "$@"
