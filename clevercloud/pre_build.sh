#!/bin/bash -l

git clone $ITOU_SECRETS_HTTPS_REPO_URL secrets-vault
wget https://github.com/mozilla/sops/releases/download/v3.7.3/sops-v3.7.3.linux -O sops
chmod +x sops
./sops -d secrets-vault/c1/$ITOU_ENVIRONMENT.enc.env > .env
