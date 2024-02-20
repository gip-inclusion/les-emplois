#!/bin/bash

OUTPUT_PATH=shared_bucket/imports-asp

# This shell script is meant to be run in production as part of a github workflow.
#
# It runs the frequent ASP data imports:
# - populate_metabase_fluxiae.py.
# - import_siae.py
# - import_ea_eatt.py
# More details about this process:
# https://github.com/betagouv/itou-private/blob/master/docs/supportix/import_asp.md

echo "Running the ASP import script"

# Activate trace of all the executed commands so that the output can be read more easily
# Every command in this script will be written before being executed
set +x

cd "$APP_HOME" || exit

FLUX_IAE_FILE=$(find asp_shared_bucket/ -name 'fluxIAE_*.zip' -type f -mtime -5)
if [[ ! -f "$FLUX_IAE_FILE" ]]; then
    echo "Missing the flux IAE file."
    exit 0
fi

CONTACT_EA_FILE=$(find asp_shared_bucket/ -name 'Liste_Contact_EA_*.zip' -type f -mtime -5)
if [[ ! -f "$CONTACT_EA_FILE" ]]; then
    echo "Missing the contact EA file."
    exit 0
fi

# Create the "data" directory inside of the app and clear it of any previously existing data
mkdir -p itou/companies/management/commands/data/
rm -rf itou/companies/management/commands/data/*

# Unzip ASP files
unzip -P "$ASP_UNZIP_PASSWORD" "$FLUX_IAE_FILE" -d itou/companies/management/commands/data/
unzip -P "$ASP_UNZIP_PASSWORD" "$CONTACT_EA_FILE" -d itou/companies/management/commands/data/

# Perform the necessary data imports
mkdir -p $OUTPUT_PATH/populate_metabase_fluxiae
mkdir -p $OUTPUT_PATH/import_siae
mkdir -p $OUTPUT_PATH/import_ea_eatt

time ./manage.py populate_metabase_fluxiae --verbosity 2 |& tee -a "$OUTPUT_PATH/populate_metabase_fluxiae/output_$(date '+%Y-%m-%d_%H-%M-%S').log"
time ./manage.py import_siae --verbosity=2 |& tee -a "$OUTPUT_PATH/import_siae/output_$(date '+%Y-%m-%d_%H-%M-%S').log"
time ./manage.py import_ea_eatt --wet-run --verbosity=2 |& tee -a "$OUTPUT_PATH/import_ea_eatt/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

# Destroy the cleartext ASP data
rm -rf itou/companies/management/commands/data/

# Remove ASP files older than 3 weeks
find asp_shared_bucket/ -name '*.zip' -type f -mtime +20 -delete
