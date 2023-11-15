#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit

set -o pipefail
set -o errexit

OUTPUT_PATH=shared_bucket/populate_metabase_matomo
mkdir -p $OUTPUT_PATH

OUTPUT_LOG="$OUTPUT_PATH/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

django-admin send_slack_message ":rocket: Démarrage de la mise à jour des données Matomo"
django-admin populate_metabase_matomo --wet-run |& tee -a "$OUTPUT_LOG"
django-admin populate_metabase_emplois --mode dbt_daily |& tee -a "$OUTPUT_LOG"
django-admin send_slack_message  ":white_check_mark: Mise à jour des données Matomo terminée"
