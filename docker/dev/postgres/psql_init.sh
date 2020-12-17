#!/bin/bash
set -e

# Initialization script.
# https://hub.docker.com/_/postgres/#initialization-scripts

export BASE_DIR=$(dirname "$BASH_SOURCE")

# We activate extensions in template1: when you create a new database you get an exact copy of template1.
PGUSER="$POSTGRES_USER" PGDATABASE="template1" bash $BASE_DIR/psql_extensions.sh
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL

  \c postgres;

  CREATE USER $ITOU_POSTGRES_USER WITH ENCRYPTED PASSWORD '$ITOU_POSTGRES_PASSWORD';
  CREATE DATABASE $ITOU_POSTGRES_DATABASE_NAME OWNER $ITOU_POSTGRES_USER;
  ALTER USER $ITOU_POSTGRES_USER CREATEDB;

EOSQL
