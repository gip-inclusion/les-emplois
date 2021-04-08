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

# To add a new extension, simply add it to a Django migration
# -----------------------------------------------------------------

echo "Loading cities"
PGPASSWORD=$POSTGRESQL_ADDON_PASSWORD pg_restore -d $REVIEW_APP_DB_NAME -h $POSTGRESQL_ADDON_HOST -p $POSTGRESQL_ADDON_PORT -U $POSTGRESQL_ADDON_USER --if-exists --clean --no-owner --no-privileges $APP_HOME/itou/fixtures/postgres/cities.sql

# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
echo "Loading fixtures"
ls -d $APP_HOME/itou/fixtures/django/* | xargs django-admin loaddata
