#!/bin/sh

###################################################################
###################### Review apps entrypoint #####################
###################################################################

# Skip this step when redeploying a review app.
if [ "$SKIP_FIXTURES" = true ] ; then
    echo "Skipping fixtures."
    exit
fi

echo "Loading cities"
PGPASSWORD=$POSTGRESQL_ADDON_PASSWORD \
    psql \
    --dbname "$POSTGRESQL_ADDON_DB" \
    --host "$POSTGRESQL_ADDON_HOST" \
    --port "$POSTGRESQL_ADDON_PORT" \
    --username "$POSTGRESQL_ADDON_USER" \
    --file "$APP_HOME"/itou/fixtures/postgres/cities.sql \
    --quiet

# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
echo "Loading fixtures"
ls -d "$APP_HOME"/itou/fixtures/django/* | xargs django-admin loaddata
