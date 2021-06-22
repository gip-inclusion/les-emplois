#!/bin/bash

# Ensure working directory in version branch clean
if ! git diff-index --quiet HEAD; then
  echo "Working directory not clean, please commit your changes first"
  exit
fi

# Merge master into master_clever, then push master_clever
# Deployment to Clever Cloud is actually triggered via a hook
# on a push on this branch
git checkout master
git pull origin master
git checkout master_clever 
git pull origin master_clever 
git merge master --no-edit
git push origin master_clever 
