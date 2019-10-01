#!/bin/bash
set -e

# Initialization script.
# https://hub.docker.com/_/postgres/#initialization-scripts

# Creating a spatial database
# https://docs.djangoproject.com/en/dev/ref/contrib/gis/install/postgis/#creating-a-spatial-database
# We activate postgis in template1: when you create a new database you get an exact copy of template1.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL

  \c template1;

  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS unaccent;

  DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
  CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
  ALTER TEXT SEARCH CONFIGURATION french_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, french_stem;

  \c postgres;

  CREATE USER $ITOU_POSTGRES_USER WITH ENCRYPTED PASSWORD '$ITOU_POSTGRES_PASSWORD';
  CREATE DATABASE $ITOU_POSTGRES_DATABASE_NAME OWNER $ITOU_POSTGRES_USER;
  ALTER USER $ITOU_POSTGRES_USER CREATEDB;

EOSQL
