#!/usr/bin/env bash

FIXTURES_DIRECTORY=$(dirname "$0")

echo "Dump models data into $FIXTURES_DIRECTORY"
./manage.py dumpdata --format json-no-auto-fields --indent 2 users.user -o "$FIXTURES_DIRECTORY/05_test_users.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 account.emailaddress -o "$FIXTURES_DIRECTORY/06_confirmed_emails.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 users.jobseekerprofile -o "$FIXTURES_DIRECTORY/07_jobseeker_profile.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.company -o "$FIXTURES_DIRECTORY/10_companies.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.siaeconvention -o "$FIXTURES_DIRECTORY/11_siae_conventions.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.siaefinancialannex -o "$FIXTURES_DIRECTORY/12_siae_financial_annexes.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.companymembership -o "$FIXTURES_DIRECTORY/13_company_memberships.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 prescribers.prescriberorganization -o "$FIXTURES_DIRECTORY/14_prescribers.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 prescribers.prescribermembership -o "$FIXTURES_DIRECTORY/15_prescriber_memberships.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 institutions.institution -o "$FIXTURES_DIRECTORY/16_institutions.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 institutions.institutionmembership -o "$FIXTURES_DIRECTORY/17_institution_memberships.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.eligibilitydiagnosis -o "$FIXTURES_DIRECTORY/20_eligibility_diagnoses.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 approvals.approval -o "$FIXTURES_DIRECTORY/21_approvals.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 employee_record.employeerecord -o "$FIXTURES_DIRECTORY/22_employee_records.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 approvals.poleemploiapproval -o "$FIXTURES_DIRECTORY/23_pe_approvals.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 job_applications.jobapplication -o "$FIXTURES_DIRECTORY/24_job_applications.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.jobdescription -o "$FIXTURES_DIRECTORY/25_job_descriptions.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 gps.followupgroup -o "$FIXTURES_DIRECTORY/26_follow_up_groups.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 gps.followupgroupmembership -o "$FIXTURES_DIRECTORY/27_follow_up_group_memberships.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 geiq.implementationassessmentcampaign -o "$FIXTURES_DIRECTORY/28_implementation_assessment_campaigns.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 geiq.implementationassessment -o "$FIXTURES_DIRECTORY/29_implementation_assessment.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.geiqeligibilitydiagnosis -o "$FIXTURES_DIRECTORY/30_geiq_eligibility_diagnoses.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.geiqselectedadministrativecriteria -o "$FIXTURES_DIRECTORY/31_geiq_selected_administrative_criteria.json"


for file in $(find "$FIXTURES_DIRECTORY" -iname '*.json' | sort); do
    jq . --sort-keys "$file" | sponge "$file"
done
