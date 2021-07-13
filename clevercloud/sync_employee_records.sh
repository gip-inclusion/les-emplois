
#!/bin/bash -l

# Fetch and upload files to ASP SFTP server

#
# About clever cloud cronjobs:
# https://www.clever-cloud.com/doc/tools/crons/
#

if [[ "$INSTANCE_NUMBER" != "0" ]]; then
    echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
    exit 0
fi

# $APP_HOME is set by default by clever cloud.
cd $APP_HOME

django-admin transfer_employee_records --download
