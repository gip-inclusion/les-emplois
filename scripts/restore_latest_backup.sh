#!/bin/bash

# Restore the latest database dump kept on Scaleway to the local database.
# Default database is $PGDATABASE but you can add a positional argument to change it.
# For example: `./restore_latest_backup.sh itou-test`
# Make sure you installed the `itou-backups` project before. Also, check that a database server is running.
# $PATH_TO_ITOU_BACKUPS is mandatory.
source "$PATH_TO_ITOU_BACKUPS/.env"

db_name="${1:-$PGDATABASE}"
backup_folder="${PATH_TO_ITOU_BACKUPS}/backups"
default_rclone_conf="$HOME/.config/rclone/rclone.conf"
rclone_conf="${PATH_TO_RCLONE_CONF:-$default_rclone_conf}"

rclone_last_backup="$(rclone lsf --config "$rclone_conf" --files-only --max-age 24h emplois:/encrypted-backups)"
rclone copy  --config "$rclone_conf" --max-age 24h --progress "emplois:/encrypted-backups/${rclone_last_backup}" "$backup_folder"
backup_file="${backup_folder}/${rclone_last_backup}"
echo "Restoring ${backup_file} to ${db_name} database"
pg_restore --dbname="${db_name}" --format=c --clean --no-owner --jobs=4 --verbose "${backup_file}"
# Make sure we don't keep a copy for too long.
rm "$backup_file"
echo "Restoration is over!"
