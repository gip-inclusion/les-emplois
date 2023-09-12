#!/bin/sh

###################################################################
###################### Review apps entrypoint #####################
###################################################################

# Skip this step when redeploying a review app.
if [ "$SKIP_FIXTURES" = true ] ; then
    echo "Skipping fixtures."
    exit
fi

echo "Loading data"
PGPASSWORD=$POSTGRESQL_ADDON_PASSWORD \
PGDATABASE=$POSTGRESQL_ADDON_DB \
PGHOST=$POSTGRESQL_ADDON_HOST \
PGPORT=$POSTGRESQL_ADDON_PORT \
PGUSER="$POSTGRESQL_ADDON_USER" \
make --directory "$APP_HOME" populate_db
