#!/bin/bash

# This script creates a machine on Clever Cloud that is then used in order to perform the database imports
# It is meant to be run from the root (./scripts/create-fast-machine.sh)

# It requires clever tools in order to be run:
# - https://github.com/CleverCloud/clever-tools/
# - https://www.clever-cloud.com/doc/getting-started/cli/

RUN_DIRECTORY=$(dirname "$0")
if [[ ! $RUN_DIRECTORY =~ "scripts" ]]; then
   echo "This script is meant to be run from the root of the project, in order to properly load everything, like this:"
   echo "./scripts/$(basename "$0")"
   exit 1
fi

if [ ! -f "$HOME/.config/clever-cloud/clever-tools.json" ]; then
  echo "clever-tools doesn't seems to be initialized, run 'clever login' to do so."
  exit 1
fi

APP_NAME=c1-fast-machine-$(date +%y-%m-%d-%Hh-%M)

clever create "$APP_NAME" --type python --region par --alias "$APP_NAME" --org Itou
clever link "$APP_NAME" --org Itou
clever scale --flavor XL --alias "$APP_NAME"

clever env set ITOU_ENVIRONMENT "FAST-MACHINE" --alias "$APP_NAME"

clever service link-addon c1-bucket-config --alias "$APP_NAME"
clever service link-addon c1-deployment-config --alias "$APP_NAME"
clever service link-addon c1-imports-config --alias "$APP_NAME"
clever service link-addon c1-prod-database-encrypted --alias "$APP_NAME"
clever service link-addon c1-redis --alias "$APP_NAME"
clever service link-addon c1-s3 --alias "$APP_NAME"

git fetch
clever deploy --alias "$APP_NAME" --branch origin/master --force

cat << EOF

🎉 Le déploiement est terminé 🎉

Vous pouvez maintenant:
 - ✈️ Aller sur la machine:
    clever ssh --alias "$APP_NAME"
 - 🔨 Jouer un script d’import, par ex:
    cd ~/app_* && ./scripts/imports-asp.sh
 - 🍺 Supprimer la machine:
    clever delete --alias $APP_NAME --yes && git remote remove "$APP_NAME"
EOF

exit 0
