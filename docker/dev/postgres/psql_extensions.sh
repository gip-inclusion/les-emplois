#!/bin/bash
set -e

if [ -z "$PGURI" ]
then
      echo "No URI specified. Using standard Postgresql environment variables."
fi

# Creating a spatial database
# https://docs.djangoproject.com/en/dev/ref/contrib/gis/install/postgis/#creating-a-spatial-database
psql -v ON_ERROR_STOP=1 $PGURI <<-EOSQL

  CREATE EXTENSION IF NOT EXISTS btree_gist;
  CREATE EXTENSION IF NOT EXISTS citext;
  CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS postgis;
  CREATE EXTENSION IF NOT EXISTS unaccent;

  DROP TEXT SEARCH CONFIGURATION IF EXISTS french_unaccent;
  CREATE TEXT SEARCH CONFIGURATION french_unaccent ( COPY = french );
  ALTER TEXT SEARCH CONFIGURATION french_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, french_stem;

EOSQL
