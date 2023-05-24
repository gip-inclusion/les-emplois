#!/bin/bash -l

# Do not run if this env var is not set:
if [[ "$EMPLOYEE_RECORD_CRON_ENABLED" != "1" ]]; then
    exit 0
fi

# About clever cloud cronjobs:
# https://www.clever-cloud.com/doc/administrate/cron/#deduplicating-crons
if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

# $APP_HOME is set by default by clever cloud.
cd "$APP_HOME" || exit

django-admin archive_employee_records --wet-run
