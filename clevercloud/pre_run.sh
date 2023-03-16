#!/bin/bash -l

cd secrets-vault || exit
git pull
cd - || exit
sops -d secrets-vault/c1/"$ITOU_ENVIRONMENT".enc.env > .env
