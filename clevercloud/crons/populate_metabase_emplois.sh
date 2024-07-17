#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit

set -o pipefail
set -o errexit

OUTPUT_PATH=shared_bucket/populate_metabase_emplois
mkdir -p $OUTPUT_PATH

OUTPUT_LOG="$OUTPUT_PATH/output_$(date '+%Y-%m-%d_%H-%M-%S').log"

# NOTE(vperron): this is not a proper getopt parsing but getopt is SO verbose for
# just that simple use that I have rather use a very simple version. This script
# is intended to be automated by a proper tool like Airflow anyway.
if [[ "$1" == "--daily" ]]; then
    django-admin send_slack_message ":rocket: lancement mise à jour de données C1 -> Metabase"
    django-admin populate_metabase_emplois --mode=enums |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=analytics |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=siaes |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=job_descriptions |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=organizations |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=job_seekers |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=criteria |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=job_applications |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=selected_jobs |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=approvals |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=prolongations |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=prolongation_requests |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=institutions |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=evaluation_campaigns |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=evaluated_siaes |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=evaluated_job_applications |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=evaluated_criteria |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=users |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=memberships |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=dbt_daily |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=gps_groups |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=gps_memberships |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=data_inconsistencies |& tee -a "$OUTPUT_LOG"
    django-admin send_slack_message ":white_check_mark: succès mise à jour de données C1 -> Metabase"
elif [[ "$1" == "--monthly" ]]; then
    django-admin send_slack_message ":rocket: lancement mise à jour de données peu fréquentes C1 -> Metabase"
    django-admin populate_metabase_emplois --mode=rome_codes |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=insee_codes |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=insee_codes_vs_post_codes |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=departments |& tee -a "$OUTPUT_LOG"
    django-admin populate_metabase_emplois --mode=dbt_daily |& tee -a "$OUTPUT_LOG"
    django-admin send_slack_message ":white_check_mark: succès mise à jour de données peu fréquentes C1 -> Metabase"
else
    echo "populate_metabase_emplois shell script: unknown mode='$1' selected"
fi

