#!/bin/sh
set -e

while ! pg_isready -h $POSTGRESQL_ADDON_HOST -p $POSTGRESQL_ADDON_PORT; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

# # https://github.com/docker/compose/issues/1926#issuecomment-422351028
# trap : TERM INT
# tail -f /dev/null & wait

django-admin migrate
django_admin import_cities
django_admin loaddata itou/fixtures/jobs.json
django_admin loaddata itou/fixtures/siaes.json
django_admin loaddata itou/fixtures/prescribers.json
django_admin loaddata itou/fixtures/test_users.json
django_admin loaddata itou/fixtures/prescriber_memberships.json
django_admin loaddata itou/fixtures/siae_memberships.json

django-admin runserver_plus 0.0.0.0:8000

exec "$@"
