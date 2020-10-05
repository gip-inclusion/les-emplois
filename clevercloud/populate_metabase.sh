#!/bin/bash -l

#
# About clever cloud cronjobs:
# https://www.clever-cloud.com/doc/tools/crons/
#

# Avoid running multiple instances of the cron in case we have several
# clever cloud instances.
if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

# $APP_HOME is set by default by clever cloud.
cd $APP_HOME

django-admin populate_metabase --verbosity 2
