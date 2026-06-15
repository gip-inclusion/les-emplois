#!/usr/bin/env bash

FIXTURES_DIRECTORY=$(dirname "$0")

echo "Dump models data into $FIXTURES_DIRECTORY"
./manage.py dumpdata --format json-no-auto-fields --indent 2 account.emailaddress -o "$FIXTURES_DIRECTORY/account__email_address.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 approvals.approval -o "$FIXTURES_DIRECTORY/approvals__approval.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.company -o "$FIXTURES_DIRECTORY/companies__company.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.companymembership -o "$FIXTURES_DIRECTORY/companies__company_membership.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.contract -o "$FIXTURES_DIRECTORY/companies__contract.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.jobdescription -o "$FIXTURES_DIRECTORY/companies__job_description.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.siaeconvention -o "$FIXTURES_DIRECTORY/companies__siae_convention.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 companies.siaefinancialannex -o "$FIXTURES_DIRECTORY/companies__siae_financial_annexe.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.eligibilitydiagnosis -o "$FIXTURES_DIRECTORY/eligibility__eligibility_diagnosis.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.geiqeligibilitydiagnosis -o "$FIXTURES_DIRECTORY/eligibility__geiq_eligibility_diagnosis.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 eligibility.geiqselectedadministrativecriteria -o "$FIXTURES_DIRECTORY/eligibility__geiq_selected_administrative_criteria.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 employee_record.employeerecord -o "$FIXTURES_DIRECTORY/employee_record__employee_record.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 geiq_assessments.assessmentcampaign -o "$FIXTURES_DIRECTORY/geiq_assessments__assessment_campaign.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 geiq_assessments.labelinfos -o "$FIXTURES_DIRECTORY/geiq_assessments__label_infos.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 gps.followupgroup -o "$FIXTURES_DIRECTORY/gps__follow_up_group.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 gps.followupgroupmembership -o "$FIXTURES_DIRECTORY/gps__follow_up_group_membership.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 insertion.genericreferenceitem -o "$FIXTURES_DIRECTORY/insertion__genericreferenceitem.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 insertion.service -o "$FIXTURES_DIRECTORY/insertion__service.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 insertion.structure -o "$FIXTURES_DIRECTORY/insertion__structure.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 institutions.institution -o "$FIXTURES_DIRECTORY/institutions__institution.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 institutions.institutionmembership -o "$FIXTURES_DIRECTORY/institutions__institution_membership.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 job_applications.jobapplication -o "$FIXTURES_DIRECTORY/job_applications__jobapplication.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 prescribers.prescriberorganization -o "$FIXTURES_DIRECTORY/prescribers__organization.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 prescribers.prescribermembership -o "$FIXTURES_DIRECTORY/prescribers_prescriber_membership.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 rdv_insertion.invitationrequest -o "$FIXTURES_DIRECTORY/rdv_insertion__invitation_request.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 rdv_insertion.invitation -o "$FIXTURES_DIRECTORY/rdv_insertion__invitation.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 rdv_insertion.location -o "$FIXTURES_DIRECTORY/rdv_insertion__location.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 rdv_insertion.appointment -o "$FIXTURES_DIRECTORY/rdv_insertion__appointment.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 rdv_insertion.participation -o "$FIXTURES_DIRECTORY/rdv_insertion__participation.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 users.jobseekerassignment -o "$FIXTURES_DIRECTORY/users__job_seeker_assignment.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 users.jobseekerprofile -o "$FIXTURES_DIRECTORY/users__jobseeker_profile.json"
./manage.py dumpdata --format json-no-auto-fields --indent 2 users.user -o "$FIXTURES_DIRECTORY/users__user.json"


for file in $(find "$FIXTURES_DIRECTORY" -iname '*.json' | sort); do
    jq . --sort-keys "$file" > tempfile
    mv tempfile "$file"
done
