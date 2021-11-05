#!/bin/bash

# This shell script is meant to be run in production as part of a github workflow.
#
# It runs the frequent ASP data imports:
# - populate_metabase_fluxiae.py.
# - import_siae.py
# - import_ea_eatt.py
# More details about this process:
# https://github.com/betagouv/itou-private/blob/master/docs/supportix/import_asp.md

echo "Running the ASP import script"

cd $APP_HOME

# creates the "data" directory inside of the app and clear it of any previously existing data
mkdir -p itou/siaes/management/commands/data/
rm -rf itou/siaes/management/commands/data/*

# Unzip ASP files
unzip -P $ASP_UNZIP_PASSWORD asp_shared_bucket/fluxIAE_*.zip -d itou/siaes/management/commands/data/
unzip -P $ASP_UNZIP_PASSWORD asp_shared_bucket/Liste_Contact_EA*.zip -d itou/siaes/management/commands/data/

# Perform the necessary data imports
time ./manage.py populate_metabase_fluxiae --verbosity 2
time ./manage.py import_siae --verbosity=2
time ./manage.py import_ea_eatt --verbosity=2

# Destroy the cleartext ASP data
rm -rf itou/siaes/management/commands/data/
