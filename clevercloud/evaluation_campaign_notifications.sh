#! /bin/bash -l

if [[ "$INSTANCE_NUMBER" != "0" ]]; then
  echo "Instance number is ${INSTANCE_NUMBER}. Stop here."
  exit 0
fi

if [[ "$CRON_ENABLED" != "1" ]]; then
  echo "Cron workers not enabled."
  exit 0
fi

cd ${APP_HOME} # Which has been loaded by the env.

django-admin evaluation_campaign_notify
