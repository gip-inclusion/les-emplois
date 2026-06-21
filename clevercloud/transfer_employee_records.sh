#!/bin/bash -l

set -u

if [[ "$CRON_ENABLED" != "1" ]]; then
    echo "Crons not enabled."
    exit 0
fi

if [[ "$EMPLOYEE_RECORD_CRON_ENABLED" != "1" ]]; then
    exit 0
fi

# About clever cloud cronjobs:
# https://www.clever.cloud/developers/doc/administrate/cron/#deduplicating-crons
if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

# TEMPORARILY disable cronjobs.
# FIXME: restore when ASP has deployed their changes.
exit 0

cd "$APP_HOME" || exit
 # shellcheck disable=SC2317
django-admin transfer_employee_records --wet-run "$@"
 # shellcheck disable=SC2317
django-admin transfer_employee_records_updates --wet-run "$@"
