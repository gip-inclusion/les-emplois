#!/bin/sh

###################################################################
########################## Demo entrypoint ########################
###################################################################

# ///////////////////////////// ! \\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
# The demo uses the same CC instance as review apps but with
# its own database.

# -----------------------------------------------------------------
# -------------------- A note on the Database ---------------------
# -----------------------------------------------------------------
# Review apps share the same Clever Cloud Postgresql add-on,
# review_apps_databases, creating a new database for each one.
# This is a workaround and may change in the future when
# it will be possible to pay add-ons when we use it,(per usage),
# and not in advance (per month).

# The command CREATE DATABASE works by copying an existing database.
# By default, it copies the standard system database named template1.
# cf https://www.postgresql.org/docs/current/manage-ag-templatedbs.html

# /!\ That is why the following instructions were added manually to the
# configured addon.
# If you update docker/dev/postgres/psql_init.sh, make sure to
# reflect it on Clever Cloud.

# ```
#   \c template1;

#   CREATE EXTENSION IF NOT EXISTS pg_trgm;
#   CREATE EXTENSION IF NOT EXISTS postgis;
#   CREATE EXTENSION IF NOT EXISTS unaccent;
#   CREATE EXTENSION IF NOT EXISTS citext;

#   DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
#   CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
#   ALTER TEXT SEARCH CONFIGURATION french_unaccent
#   ALTER MAPPING FOR hword, hword_part, word
#   WITH unaccent, french_stem;
# ```
# -----------------------------------------------------------------

# Delete everything
django-admin flush

# Restore cities
# First, delete all references to an "itou" role from the SQL dump.
# Then, load data
# /!\ The database is not the standard one! Use the $DEMO_APP_DB_NAME variable.
cat itou/fixtures/postgres/cities.sql | awk '!/itou/' | psql -d $DEMO_APP_DB_NAME -h $POSTGRESQL_ADDON_DIRECT_HOST -p $POSTGRESQL_ADDON_DIRECT_PORT -U $POSTGRESQL_ADDON_USER

# Now load fixtures while taking a break. 
# It can last a few minutes without any sign of life coming from the shell, just wait.
ls -d itou/fixtures/django/* | xargs django-admin loaddata

# Import administrative criteria
# As data have been deleted after running migrations,
# administrative criteria are no longer in the database
# whereas the migration generating them has been completed.
# Go back to the initial migration and run them another time.
django-admin migrate eligibility 0001_initial
django-admin migrate eligibility

# Change admin password
echo "Updating super admin password"
django-admin shell <<EOF
import os
from django.contrib.auth import get_user_model
password = os.environ.get("ADMIN_PASSWORD")
user = get_user_model().objects.get(email="admin@test.com")
user.set_password(password)
user.save()
EOF
