#!/bin/bash -l

if [[ "$APPROVALS_TO_PE_CRON_ENABLED" != "1" ]]; then
    exit 0
fi

if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

cd "$APP_HOME" || exit

django-admin send_approvals_to_pe --wet-run --delay=1
