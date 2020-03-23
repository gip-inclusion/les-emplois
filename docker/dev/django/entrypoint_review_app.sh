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

# Update database to match our settings
# TODO: when Clever Cloud will be available for all environment,
# remove this and create a file for all the environments.

  # CREATE EXTENSION IF NOT EXISTS pg_trgm;
  # CREATE EXTENSION IF NOT EXISTS postgis;
  # CREATE EXTENSION IF NOT EXISTS unaccent;
psql -v ON_ERROR_STOP=1 $POSTGRESQL_ADDON_URI <<-EOSQL
  DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
  CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
  ALTER TEXT SEARCH CONFIGURATION french_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, french_stem;
EOSQL

django-admin migrate
django-admin import_cities

echo "################# Cities imported successfully. Now import all fixtures. #######################"
# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
ls -d ~/itou/fixtures/* | xargs django-admin loaddata

django-admin runserver_plus 0.0.0.0:8000

exec "$@"
