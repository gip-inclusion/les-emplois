#!/bin/bash
set -e

# Initialization script.
# https://hub.docker.com/_/postgres/#initialization-scripts

export BASE_DIR=$(dirname "$BASH_SOURCE")

# The PostgreSQL user should be able to create extensions.
# Only the PostgreSQL superuser role provides that permission.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL

  \c postgres;

  CREATE USER $ITOU_POSTGRES_USER WITH ENCRYPTED PASSWORD '$ITOU_POSTGRES_PASSWORD';
  CREATE DATABASE $ITOU_POSTGRES_DATABASE_NAME OWNER $ITOU_POSTGRES_USER;
  ALTER USER $ITOU_POSTGRES_USER CREATEDB SUPERUSER;

EOSQL
