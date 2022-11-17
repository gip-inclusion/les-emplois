#!/bin/bash -l

cd secrets-vault
git pull
cd -
sops -d secrets-vault/c1/$ITOU_ENVIRONMENT.enc.env > .env
