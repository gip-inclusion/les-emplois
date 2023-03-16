#!/bin/bash -l

# Fetch and upload files to ASP SFTP server

# Do not run if this env var is not set:
if [[ "$EMPLOYEE_RECORD_CRON_ENABLED" != "1" ]]; then
    exit 0
fi

# About clever cloud cronjobs:
# https://www.clever-cloud.com/doc/tools/crons/

if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

# $APP_HOME is set by default by clever cloud.
cd "$APP_HOME" || exit

# Check for common blocking errors before uploads
django-admin sanitize_employee_records

# Upload employee records 
django-admin transfer_employee_records --upload

# Upload update notifications 
django-admin transfer_employee_records_updates --upload --wet-run

