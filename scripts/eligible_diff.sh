#!/bin/bash

branch_to_check=$1
if [ -z "$1" ]; then
    echo "No branch given!"
    exit 255
fi

git fetch --all
echo "Checking eligible as employee record on master"
git checkout master
./manage.py count_eligible_as_employee_record > before.log
echo "Checking eligible as employee record on $branch_to_check"
git checkout "$branch_to_check"
./manage.py count_eligible_as_employee_record > after.log
echo "Diff are:"
diff before.log after.log
