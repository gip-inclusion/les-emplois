#!/bin/sh
set -e

while ! pg_isready -h $POSTGRESQL_ADDON_HOST -p $POSTGRESQL_ADDON_PORT; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

###################################################################
# Review apps share the same Clever Cloud Postgresql add-on,
# root_db, creating a new database for each one.
# This is a workaround and may change in the future when
# it will be possible to pay add-ons when we use it,(per usage),
# and not in advance (per month).
# See
###################################################################

# CREATE DATABASE actually works by copying an existing database.
# By default, it copies the standard system database named template1.
# cf https://www.postgresql.org/docs/current/manage-ag-templatedbs.html

# /!\ The following instructions were added manually to the
# configured addon:

#   \c template1;

#   CREATE EXTENSION IF NOT EXISTS pg_trgm;
#   CREATE EXTENSION IF NOT EXISTS postgis;
#   CREATE EXTENSION IF NOT EXISTS unaccent;

#   DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
#   CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
#   ALTER TEXT SEARCH CONFIGURATION french_unaccent
#   ALTER MAPPING FOR hword, hword_part, word
#   WITH unaccent, french_stem;

export POSTGRESQL_ADDON_DB=$REVIEW_APP_DB_NAME

django-admin migrate
django-admin import_cities

# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
ls -d ~/itou/fixtures/* | xargs django-admin loaddata

django-admin runserver_plus 0.0.0.0:8000

exec "$@"
