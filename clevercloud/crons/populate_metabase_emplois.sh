#!/bin/bash -l

if [[ "$CRON_ENABLED" != "1" ]]; then
    exit 0
fi

cd "$APP_HOME" || exit 1

set -xe  # check that it actually stops on first error

# FIXME(vperron): send starting slack message here

django-admin populate_metabase_itou --mode=siaes
django-admin populate_metabase_itou --mode=job_descriptions
django-admin populate_metabase_itou --mode=organizations
django-admin populate_metabase_itou --mode=job_seekers
django-admin populate_metabase_itou --mode=job_applications
django-admin populate_metabase_itou --mode=selected_jobs
django-admin populate_metabase_itou --mode=approvals
django-admin populate_metabase_itou --mode=final_tables
django-admin populate_metabase_itou --mode=inconsistencies

# FIXME(vperron): send ending slack message here

# FIXME(vperron): Those should be sent monthly.
# django-admin populate_metabase_itou --mode=rome_codes
# django-admin populate_metabase_itou --mode=insee_codes
# django-admin populate_metabase_itou --mode=departments
