#!/bin/bash
set -e

# Initialization script.
# https://hub.docker.com/_/postgres/#initialization-scripts

psql -v ON_ERROR_STOP=1 --echo-queries --command="CREATE DATABASE \"$ITOU_POSTGRES_DATABASE_NAME\";"
