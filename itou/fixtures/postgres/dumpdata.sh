#!/usr/bin/env bash

FIXTURES_DIRECTORY=$(dirname "$0")

pg_dump --no-owner --no-privileges --data-only -d itou -t cities_city > "$FIXTURES_DIRECTORY/cities_city.sql"
pg_dump --no-owner --no-privileges --data-only -d itou -t asp_commune > "$FIXTURES_DIRECTORY/asp_commune.sql"
pg_dump --no-owner --no-privileges --data-only -d itou -t asp_department > "$FIXTURES_DIRECTORY/asp_department.sql"
pg_dump --no-owner --no-privileges --data-only -d itou -t asp_country > "$FIXTURES_DIRECTORY/asp_country.sql"
pg_dump --no-owner --no-privileges --data-only -d itou -t jobs_rome > "$FIXTURES_DIRECTORY/jobs_rome.sql"
pg_dump --no-owner --no-privileges --data-only -d itou -t jobs_appellation > "$FIXTURES_DIRECTORY/jobs_appellation.sql"
