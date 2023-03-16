#!/bin/bash -l

git clone "$ITOU_SECRETS_HTTPS_REPO_URL" secrets-vault
sops -d secrets-vault/c1/"$ITOU_ENVIRONMENT".enc.env > .env
