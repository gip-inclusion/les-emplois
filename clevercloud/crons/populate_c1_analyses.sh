#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit

set -o pipefail
set -o errexit

OUTPUT_PATH=shared_bucket/populate_c1_analyses
mkdir -p $OUTPUT_PATH

OUTPUT_LOG="$OUTPUT_PATH/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

django-admin populate_c1_analyses --wet-run |& tee -a "$OUTPUT_LOG"
