#!/bin/bash

# Restore the latest database dump kept on Scaleway to the local database.
# Default database is $PGDATABASE but you can add a positional argument to change it.
# For example: `./restore_latest_backup.sh itou-test`
# Make sure you installed the `itou-backups` project before. Also, check that a database server is running.
# $PATH_TO_ITOU_BACKUPS is mandatory.

if [ ! -f "$PATH_TO_ITOU_BACKUPS/.env" ]; then
    echo "Itou backups .env file not found. Stopping here."
    exit 0
fi

# https://www.shellcheck.net/wiki/SC1091
# shellcheck disable=SC1091
source "$PATH_TO_ITOU_BACKUPS/.env"

db_name="${1:-$PGDATABASE}"
backup_folder="${PATH_TO_ITOU_BACKUPS}/backups"
export RCLONE_CONFIG=${RCLONE_CONFIG:-"$PATH_TO_ITOU_BACKUPS/rclone.conf"}

rclone_last_backup="$(rclone lsf --files-only --max-age 24h emplois:/encrypted-backups)"
rclone copy --max-age 24h --progress "emplois:/encrypted-backups/${rclone_last_backup}" "$backup_folder"
backup_file="${backup_folder}/${rclone_last_backup}"
echo "Restoring ${backup_file} to ${db_name} database"
pg_restore --dbname="${db_name}" --format=c --clean --no-owner --jobs=4 --verbose "${backup_file}"
# Make sure we don't keep a copy for too long.
rm "$backup_file"
echo "Restoration is over!"
