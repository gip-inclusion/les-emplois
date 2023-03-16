#!/bin/bash -l

set -ue

if [[ "$CRON_ENABLED" != "1" ]]; then
    echo "Crons not enabled."
    exit 0
fi

cd "$APP_HOME"
django-admin $@
