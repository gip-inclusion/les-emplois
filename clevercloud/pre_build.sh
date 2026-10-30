#!/bin/bash -l

set -ue

git clone "$ITOU_SECRETS_HTTPS_REPO_URL" secrets-vault
sops -d secrets-vault/c1/"$ITOU_ENVIRONMENT".enc.env > .env

# Clever Cloud installs the dependencies with pip, from a requirements file
uv export --quiet --frozen --no-dev --format requirements-txt --output-file "${CC_PIP_REQUIREMENTS_FILE:-requirements.txt}"
