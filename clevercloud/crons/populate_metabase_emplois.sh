#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit 1

set -o errexit

# NOTE(vperron): this is not a proper getopt parsing but getopt is SO verbose for
# just that simple use that I have rather use a very simple version. This script
# is intended to be automated by a proper tool like Airflow anyway.
if [[ "$1" == "--daily" ]]; then
    django-admin send_slack_message ":rocket: lancement mise à jour de données C1 -> Metabase"
    django-admin populate_metabase_emplois --mode=siaes
    django-admin populate_metabase_emplois --mode=job_descriptions
    django-admin populate_metabase_emplois --mode=organizations
    django-admin populate_metabase_emplois --mode=job_seekers
    django-admin populate_metabase_emplois --mode=job_applications
    django-admin populate_metabase_emplois --mode=selected_jobs
    django-admin populate_metabase_emplois --mode=approvals
    django-admin populate_metabase_emplois --mode=final_tables
    django-admin populate_metabase_emplois --mode=data_inconsistencies
    django-admin send_slack_message ":white_check_mark: succès mise à jour de données C1 -> Metabase"
elif [[ "$1" == "--monthly" ]]; then
    django-admin send_slack_message ":rocket: lancement mise à jour de données peu fréquentes C1 -> Metabase"
    django-admin populate_metabase_emplois --mode=rome_codes
    django-admin populate_metabase_emplois --mode=insee_codes
    django-admin populate_metabase_emplois --mode=departments
    django-admin populate_metabase_emplois --mode=final_tables
    django-admin send_slack_message ":white_check_mark: succès mise à jour de données peu fréquentes C1 -> Metabase"
else
    echo "populate_metabase_emplois shell script: unknown mode='$1' selected"
fi
