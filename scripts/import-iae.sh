#!/bin/bash
# Activate trace of all the executed commands so that the output can be read more easily
# Every command in this script will be written before being executed
set +x

echo "Running the ASP import script for IAE"
cd "$APP_HOME" || exit

FLUX_IAE_FILE_GLOB='fluxIAE_*.zip'

FLUX_IAE_FILE=$(find dgefp_shared_bucket/ -name "$FLUX_IAE_FILE_GLOB" -type f -mtime -5)
if [[ ! -f "$FLUX_IAE_FILE" ]]; then
    echo "Missing the flux IAE file."
    exit 0
fi

FLUX_IAE_DIR=$(realpath "itou/companies/management/commands/data/")

# Create the "data" directory inside of the app and clear it of any previously existing data
mkdir -p "$FLUX_IAE_DIR"
rm -rf "$FLUX_IAE_DIR"*

# Unzip files
unzip -P "$ASP_UNZIP_PASSWORD" "$FLUX_IAE_FILE" -d "$FLUX_IAE_DIR"

# Create the logs directory
OUTPUT_PATH="shared_bucket/imports-asp"
mkdir -p "$OUTPUT_PATH/populate_metabase_fluxiae"
mkdir -p "$OUTPUT_PATH/import_siae"

# Perform the necessary data imports
export ASP_FLUX_IAE_DIR="$FLUX_IAE_DIR"
time ./manage.py populate_metabase_fluxiae --verbosity 2 |& tee -a "$OUTPUT_PATH/populate_metabase_fluxiae/output_$(date '+%Y-%m-%d_%H-%M-%S').log"
time ./manage.py import_siae --wet-run --verbosity=2 |& tee -a "$OUTPUT_PATH/import_siae/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

# Destroy the cleartext data
rm -rf "$FLUX_IAE_DIR"

# Remove files older than 3 weeks
find dgefp_shared_bucket/ -name "$FLUX_IAE_FILE_GLOB" -type f -mtime +20 -delete
