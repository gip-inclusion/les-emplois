#!/bin/sh

###################################################################
###################### Review apps entrypoint #####################
###################################################################

# -----------------------------------------------------------------
# -------------------- A note on the Database ---------------------
# Review apps share the same Clever Cloud Postgresql add-on,
# review_apps_databases, creating a new database for each one.
# This is a workaround and may change in the future when
# it will be possible to pay add-ons when we use it,(per usage),
# and not in advance (per month).

# The command CREATE DATABASE works by copying an existing database.
# By default, it copies the standard system database named template1.
# cf https://www.postgresql.org/docs/current/manage-ag-templatedbs.html

# /!\ That is why the following instructions were added manually to the
# configured addon.
# If you update docker/dev/postgres/psql_init.sh, make sure to
# reflect it on Clever Cloud.

# ```
#   \c template1;

#   CREATE EXTENSION IF NOT EXISTS btree_gist;
#   CREATE EXTENSION IF NOT EXISTS citext;
#   CREATE EXTENSION IF NOT EXISTS pg_trgm;
#   CREATE EXTENSION IF NOT EXISTS postgis;
#   CREATE EXTENSION IF NOT EXISTS unaccent;

#   DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
#   CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
#   ALTER TEXT SEARCH CONFIGURATION french_unaccent
#   ALTER MAPPING FOR hword, hword_part, word
#   WITH unaccent, french_stem;
# ```
# -----------------------------------------------------------------

set -e

while ! pg_isready -h $POSTGRESQL_ADDON_HOST -p $POSTGRESQL_ADDON_PORT; do
    >&2 echo "Postgres is unavailable - sleeping"
    sleep 1
done

>&2 echo "Postgres is up - continuing"

export POSTGRESQL_ADDON_DB=$REVIEW_APP_DB_NAME

django-admin migrate
django-admin import_cities

# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
echo "Loading fixtures"
ls -d ~/itou/fixtures/* | xargs django-admin loaddata

django-admin runserver_plus 0.0.0.0:8000

exec "$@"
