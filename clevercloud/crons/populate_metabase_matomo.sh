#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit 1

django-admin populate_metabase_matomo --wet-run
# FIXME(vperron): Cannot use the generic cron wrapper yet since we should:
# - inject the build metabase final tables in python directly in the base command
# - add a way to test that script becuase for now the small mock is unsifficient
# - figure out a better way to chain those data dependencies
django-admin build_metabase_final_tables
