#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit 1

set -o errexit

django-admin send_slack_message ":rocket: Démarrage de la mise à jour des données Matomo"
django-admin populate_metabase_matomo --mode=public --wet-run
django-admin populate_metabase_matomo --mode=private --wet-run
django-admin populate_metabase_emplois --mode final_tables
django-admin send_slack_message  ":white_check_mark: Mise à jour des données Matomo terminée"
