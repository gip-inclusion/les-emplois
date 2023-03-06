#!/bin/bash

initial_branch=`git branch --show-current`

# Ensure working directory is clean
if ! git diff-index --quiet HEAD; then
  echo "Working directory not clean, please commit your changes first"
  exit
fi

# Merge master into master_clever, then push master_clever
# Deployment to Clever Cloud is actually triggered via a hook
# on a push on this branch

# synchronize master and master_clever by replaying the local branches on top of remote ones
git fetch origin
git checkout master
git rebase origin/master master
git checkout master_clever
git rebase origin/master_clever master_clever

# merge master into master_clever
git merge master --no-edit --ff-only
git push origin master_clever

# When we are done, we want to restore the initial state
# (in order to avoid writing things directly on master_clever by accident)
if [ -z $initial_branch ]; then
    # The initial_branch is empty when user is in detached state, so we simply go back to master
    git checkout master
    echo
    echo "You were on detached state before deploying, you are back to master"
else
    git checkout $initial_branch
    echo
    echo "Back to $initial_branch"
fi
