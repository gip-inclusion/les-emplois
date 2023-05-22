#!/usr/bin/bash -l

cd "${APP_HOME}" || exit
scripts/expire-elastic-indices
