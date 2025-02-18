import datetime

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.job_applications.enums import JobApplicationState
from itou.www.employee_record_views.enums import MissingEmployeeCase
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup


@freeze_time("2025-02-14")
def test_missing_employee(client, snapshot):
    siae = CompanyFactory(subject_to_eligibility=True, with_membership=True)
    user = siae.members.get()
    client.force_login(user)

    url = reverse("employee_record_views:missing_employee")

    response = client.get(url)
    assert str(parse_response_to_soup(response, selector=".s-section")) == snapshot(name="form")

    # job_seeker that was never hired
    job_seeker = JobSeekerFactory(first_name="André", last_name="Alonso")
    JobApplicationFactory(to_company=siae, job_seeker=job_seeker)
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(
        parse_response_to_soup(
            response,
            selector=".s-section",
            replace_in_attr=[
                (
                    "href",
                    f"/apply/siae/list?job_seeker={job_seeker.pk}",
                    "/apply/siae/list?job_seeker=[PK of Job seeker]",
                )
            ],
        )
    ) == snapshot(name=MissingEmployeeCase.NO_HIRING)

    # hired without approval (not possible anymore)
    job_seeker = JobSeekerFactory(first_name="Béatrice", last_name="Beauregard")
    JobApplicationFactory(to_company=siae, job_seeker=job_seeker, state=JobApplicationState.ACCEPTED, approval=None)
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(parse_response_to_soup(response, selector=".s-section")) == snapshot(
        name=MissingEmployeeCase.NO_APPROVAL
    )

    # hired in the future
    job_seeker = JobSeekerFactory(first_name="Charles", last_name="Constantin")
    approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00001")
    JobApplicationFactory(
        to_company=siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 2, 15),
    )
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(parse_response_to_soup(response, selector=".s-section")) == snapshot(
        name=MissingEmployeeCase.FUTURE_HIRING
    )

    # But if there also was a previous accepted job application it works
    job_application = JobApplicationFactory(
        to_company=siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 1, 1),
        created_at=timezone.now() - datetime.timedelta(days=1),  # fallback for accepted_at
    )
    response = client.post(url, data={"employee": job_seeker.pk})
    assert response.context["approvals_data"][0][2] == MissingEmployeeCase.NO_EMPLOYEE_RECORD

    # hired and already has an employee record
    job_seeker = JobSeekerFactory(first_name="Damien", last_name="Danone")
    approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00002")
    job_application = JobApplicationFactory(
        to_company=siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 2, 14),
    )
    employee_record = EmployeeRecordFactory(job_application=job_application)
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(
        parse_response_to_soup(
            response,
            selector=".s-section",
            replace_in_attr=[
                (
                    "href",
                    f"/employee_record/summary/{employee_record.pk}",
                    "/employee_record/summary/[PK of EmployeeRecord]",
                )
            ],
        )
    ) == snapshot(name=MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_SAME_COMPANY)

    # hired and already has an employee record in another siae on the same convention
    job_seeker = JobSeekerFactory(first_name="Eliott", last_name="Emery")
    approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00003")
    JobApplicationFactory(
        to_company=siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 2, 14),
    )
    other_siae = CompanyFactory(convention=siae.convention, for_snapshot=True)
    job_application = JobApplicationFactory(
        to_company=other_siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 2, 14),
    )
    employee_record = EmployeeRecordFactory(job_application=job_application)
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(parse_response_to_soup(response, selector=".s-section")) == snapshot(
        name=MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_OTHER_COMPANY
    )

    # hired without an employee record
    job_seeker = JobSeekerFactory(first_name="Fabienne", last_name="Favriseau")
    approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00004")
    job_application = JobApplicationFactory(
        to_company=siae,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
        approval=approval,
        hiring_start_at=datetime.date(2025, 2, 14),
    )
    response = client.post(url, data={"employee": job_seeker.pk})
    assert str(
        parse_response_to_soup(
            response,
            selector=".s-section",
            replace_in_attr=[
                (
                    "href",
                    f"/employee_record/create/{job_application.pk}",
                    "/employee_record/create/[PK of JobApplication]",
                )
            ],
        )
    ) == snapshot(name=MissingEmployeeCase.NO_EMPLOYEE_RECORD)
