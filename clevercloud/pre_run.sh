#!/bin/bash -l

cd secrets-vault
git pull
cd -
sops -d secrets-vault/c1/$ITOU_ENVIRONMENT.enc.env > .env

pwd

cat clevercloud/uwsgi.ini \
| sed "s/__APP_HOME__/$APP_HOME/g" \
| sed "s/__HARAKIRI__/$HARAKIRI/g" \
| sed "s/__CC_PYTHON_MODULE__/$CC_PYTHON_MODULE/g" \
| sed "s/__WORKERS__/${WSGI_WORKERS:-2}/g" \
> uwsgi.ini
