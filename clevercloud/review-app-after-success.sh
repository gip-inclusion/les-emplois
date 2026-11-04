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
PGDATABASE="$POSTGRESQL_ADDON_DIRECT_URI" make --directory "$APP_HOME" populate_db
# Needs the demo prescriber and the reference items loaded by populate_db
PGDATABASE="$POSTGRESQL_ADDON_DIRECT_URI" python "$APP_HOME/manage.py" pass_demo_seed
