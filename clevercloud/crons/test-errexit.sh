#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit 1

set -o errexit

OUTPUT_PATH=shared_bucket/test-errexit
mkdir -p $OUTPUT_PATH

OUTPUT_LOG="$OUTPUT_PATH/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

echo "Première ligne testée" > $OUTPUT_LOG
echo "Seconde ligne testée" |& tee -a $OUTPUT_LOG

false

echo "Première ligne qui ne devrait pas exister" >> $OUTPUT_LOG
echo "Seconde ligne qui ne devrait pas exister" |& tee -a $OUTPUT_LOG

