#!/bin/bash -l

set -ue

if [[ "$CRON_ENABLED" != "1" ]]; then
    echo "Crons not enabled."
    exit 0
fi

# About clever cloud cronjobs:
# https://www.clever-cloud.com/doc/administrate/cron/#deduplicating-crons
if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

cd "$APP_HOME"
django-admin "$@"
