#!/bin/bash

# you can find me with "clever login"
source .env

if [ -z $CLEVER_TOKEN ]; then
  echo "please add 'CLEVER_TOKEN=some_token' in .env at the root of the project in order to run this script"
  exit
fi
if [ -z $CLEVER_SECRET ]; then
  echo "please add 'CLEVER_SECRET=some_secret' in .env at the root of the project in order to run this script"
  exit
fi

ITOU_ORGANIZATION_NAME=Itou
IMPORT_APP_NAME=c1-imports-$(date +%y-%m-%d-%Hh-%M)
DEPLOY_BRANCH=master_clever

clever login --token $CLEVER_TOKEN --secret $CLEVER_SECRET
# Create a new application on Clever Cloud.
# -t: application type (Python).
# --org: organization name.
# --region: server location ("par" means Paris).
# --alias: custom application name, used to find it with the CLI.
clever create $IMPORT_APP_NAME -t python --region par --alias $IMPORT_APP_NAME --org Itou
clever link $IMPORT_APP_NAME --org $ITOU_ORGANIZATION_NAME
clever scale --flavor XL --alias $IMPORT_APP_NAME
clever service link-addon c1-imports-config --alias $IMPORT_APP_NAME
clever service link-addon c1-prod-config --alias $IMPORT_APP_NAME
clever service link-addon c1-prod-database-encrypted  --alias $IMPORT_APP_NAME
clever service link-addon c1-itou-redis --alias $IMPORT_APP_NAME

clever deploy --alias $IMPORT_APP_NAME --branch $DEPLOY_BRANCH --force
