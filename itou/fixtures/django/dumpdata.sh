#!/usr/bin/env bash

FIXTURES_DIRECTORY=$(dirname "$0")

echo "Dump models data into $FIXTURES_DIRECTORY"
./manage.py dumpdata asp.commune -o "$FIXTURES_DIRECTORY/01_asp_INSEE_communes.json"
./manage.py dumpdata asp.country -o "$FIXTURES_DIRECTORY/02_asp_INSEE_countries.json"
./manage.py dumpdata asp.department -o "$FIXTURES_DIRECTORY/03_asp_INSEE_departments.json"
./manage.py dumpdata jobs.appellation jobs.rome -o "$FIXTURES_DIRECTORY/04_jobs.json"
./manage.py dumpdata users.user -o "$FIXTURES_DIRECTORY/05_test_users.json"
./manage.py dumpdata account.emailaddress -o "$FIXTURES_DIRECTORY/06_confirmed_emails.json"
./manage.py dumpdata users.jobseekerprofile -o "$FIXTURES_DIRECTORY/07_jobseeker_profile.json"
./manage.py dumpdata companies.company -o "$FIXTURES_DIRECTORY/10_companies.json"
./manage.py dumpdata companies.siaeconvention -o "$FIXTURES_DIRECTORY/11_siae_conventions.json"
./manage.py dumpdata companies.siaefinancialannex -o "$FIXTURES_DIRECTORY/12_siae_financial_annexes.json"
./manage.py dumpdata companies.companymembership -o "$FIXTURES_DIRECTORY/13_company_memberships.json"
./manage.py dumpdata prescribers.prescriberorganization -o "$FIXTURES_DIRECTORY/14_prescribers.json"
./manage.py dumpdata prescribers.prescribermembership -o "$FIXTURES_DIRECTORY/15_prescriber_memberships.json"
./manage.py dumpdata institutions.institution -o "$FIXTURES_DIRECTORY/16_institutions.json"
./manage.py dumpdata institutions.institutionmembership -o "$FIXTURES_DIRECTORY/17_institution_memberships.json"
./manage.py dumpdata eligibility.eligibilitydiagnosis -o "$FIXTURES_DIRECTORY/20_eligibility_diagnoses.json"
./manage.py dumpdata approvals.approval -o "$FIXTURES_DIRECTORY/21_approvals.json"
./manage.py dumpdata employee_record.employeerecord -o "$FIXTURES_DIRECTORY/22_employee_records.json"
./manage.py dumpdata approvals.poleemploiapproval -o "$FIXTURES_DIRECTORY/23_pe_approvals.json"
./manage.py dumpdata job_applications.jobapplication -o "$FIXTURES_DIRECTORY/24_job_applications.json"
./manage.py dumpdata companies.jobdescription -o "$FIXTURES_DIRECTORY/25_job_descriptions.json"


for file in $(find "$FIXTURES_DIRECTORY" -iname '*.json' | sort); do
    jq . --sort-keys "$file" | sponge "$file"
done
