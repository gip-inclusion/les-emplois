#!/bin/sh

###################################################################
###################### Review apps entrypoint #####################
###################################################################

echo "Loading cities"
PGPASSWORD=$POSTGRESQL_ADDON_PASSWORD pg_restore -d $POSTGRESQL_ADDON_DB -h $POSTGRESQL_ADDON_HOST -p $POSTGRESQL_ADDON_PORT -U $POSTGRESQL_ADDON_USER --if-exists --clean --no-owner --no-privileges $APP_HOME/itou/fixtures/postgres/cities.sql

# `ls $APP_HOME` does not work as the current user
# does not have execution rights on the $APP_HOME directory.
echo "Loading fixtures"
ls -d $APP_HOME/itou/fixtures/django/* | xargs django-admin loaddata

echo "Updating super admin password"
django-admin shell <<EOF
import os
from itou.users.models import User
password = os.environ.get("ADMIN_PASSWORD")
user = User.objects.get(email="admin@test.com")
user.set_password(password)
user.save()
EOF
