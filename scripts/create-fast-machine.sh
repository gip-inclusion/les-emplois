#!/bin/bash

# This script creates a machine on Clever Cloud that is then used in order to perform the database imports
# It is meant to be run from the root (./scripts/create-fast-machine.sh)

# It requires clever tools in order to be run:
# - https://github.com/CleverCloud/clever-tools/
# - https://www.clever-cloud.com/doc/getting-started/cli/

RUN_DIRECTORY=`dirname $0`
if [[ ! $RUN_DIRECTORY =~ "scripts" ]]; then
   echo "This script is meant to be run from the root of the project, in order to properly load everything, like this:"
   echo "./scripts/`basename $0`"
   exit 1
fi

# If the script is loaded from the root we can import the local environment variables
source .env
if [ -z $CLEVER_TOKEN ]; then
  echo "please add 'CLEVER_TOKEN=some_token' in .env at the root of the project in order to run this script. You can find its value with 'clever login'"
  exit 1
fi
if [ -z $CLEVER_SECRET ]; then
  echo "please add 'CLEVER_SECRET=some_secret' in .env at the root of the project in order to run this script. You can find its value with 'clever login'"
  exit 1
fi

# Then we can create the machine

ORGANIZATION_NAME=Itou
IMPORT_APP_NAME=c1-imports-$(date +%y-%m-%d-%Hh-%M)
DEPLOY_BRANCH=master_clever
CC_PYTHON_VERSION=3.10

clever login --token $CLEVER_TOKEN --secret $CLEVER_SECRET
# Create a new application on Clever Cloud.
# --type: application type (Python).
# --org: organization name.
# --region: server location ("par" means Paris).
# --alias: custom application name, used to find it with the CLI.
clever create $IMPORT_APP_NAME --type python --region par --alias $IMPORT_APP_NAME --org $ORGANIZATION_NAME
clever env set CC_PYTHON_VERSION "$CC_PYTHON_VERSION" --alias $IMPORT_APP_NAME
clever link $IMPORT_APP_NAME --org $ORGANIZATION_NAME
clever scale --flavor XL --alias $IMPORT_APP_NAME
clever service link-addon c1-imports-config --alias $IMPORT_APP_NAME
clever service link-addon c1-fast-machine-config --alias $IMPORT_APP_NAME
clever service link-addon c1-prod-database-encrypted  --alias $IMPORT_APP_NAME
clever service link-addon c1-itou-redis --alias $IMPORT_APP_NAME

# We never want huey to be run in such a machine so CC_WORKER_COMMAND must be empty.
#
# This value being incorrectly set to "django_admin run_huey" led to the epic issue of march 2022
# where an import machine unexpectedly ran huey tasks with invalid settings.
# You never want to face this kind of hard-to-debug issue ever again
clever env set CC_WORKER_COMMAND "" --alias $IMPORT_APP_NAME

clever deploy --alias $IMPORT_APP_NAME --branch $DEPLOY_BRANCH --force

cat << EOF

🎉 Le déploiement est terminé 🎉

Vous pouvez maintenant:
 - ✈️ Aller sur la machine:
    clever ssh --alias $IMPORT_APP_NAME
 - 🔨 Jouer un script d’import, par ex:
    cd ~/app_* && ./scripts/imports-asp.sh
 - 🍺 Supprimer la machine:
    clever delete --alias $IMPORT_APP_NAME --yes
EOF

exit 0
