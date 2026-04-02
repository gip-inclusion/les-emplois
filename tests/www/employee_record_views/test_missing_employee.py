import datetime

from django.urls import reverse
from freezegun import freeze_time

from itou.companies.enums import CompanySource
from itou.job_applications.enums import JobApplicationState
from itou.www.employee_record_views.enums import MissingEmployeeCase
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


@freeze_time("2025-02-14")
class TestMissingEmployee:
    def setUp(self, client):
        self.siae = CompanyFactory(kind="AI", for_snapshot=True, with_membership=True)
        self.url = reverse("employee_record_views:missing_employee")
        user = self.siae.members.get()
        client.force_login(user)

    def _extract_case(self, response) -> MissingEmployeeCase:
        if response.context["case"]:
            return response.context["case"]
        _approval, _job_application, approval_case, _ = response.context["approvals_data"][0]
        return approval_case

    def _extract_html_section(self, response, replace_in_attr=()):
        return pretty_indented(
            parse_response_to_soup(
                response,
                selector=".s-section",
                replace_in_attr=replace_in_attr,
            )
        )

    def test_get(self, client, snapshot):
        self.setUp(client)
        response = client.get(self.url)
        assert self._extract_html_section(response) == snapshot()

    def test_post_never_hired(self, client, snapshot):
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="André", last_name="Alonso")
        JobApplicationFactory(sent_by_prescriber_alone=True, to_company=self.siae, job_seeker=job_seeker)

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.NO_HIRING
        html = self._extract_html_section(
            response,
            replace_in_attr=[
                (
                    "href",
                    f"/apply/siae/list?job_seeker={job_seeker.pk}",
                    "/apply/siae/list?job_seeker=[PK of Job seeker]",
                )
            ],
        )
        assert html == snapshot()

    def test_post_hired_without_approval(self, client, snapshot):  # not possible anymore
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="Béatrice", last_name="Beauregard")
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=self.siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=None,
        )

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.NO_APPROVAL
        assert self._extract_html_section(response) == snapshot()

    def test_post_hired_with_an_approval_without_employee_record(self, client, snapshot):
        # nominal case
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="Fabienne", last_name="Favriseau")
        approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00004")
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=self.siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            hiring_start_at=datetime.date(2025, 2, 14),
        )

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.NO_EMPLOYEE_RECORD
        html = self._extract_html_section(
            response,
            replace_in_attr=[
                (
                    "href",
                    f"/employee_record/create/{job_application.pk}",
                    "/employee_record/create/[PK of JobApplication]",
                )
            ],
        )
        assert html == snapshot()

    def test_post_hired_with_employee_record_same_siae(self, client, snapshot):
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="Damien", last_name="Danone")
        approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00002")
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=self.siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            hiring_start_at=datetime.date(2025, 2, 14),
        )
        employee_record = EmployeeRecordFactory(job_application=job_application)

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_SAME_COMPANY
        html = self._extract_html_section(
            response,
            replace_in_attr=[
                (
                    "href",
                    f"/employee_record/summary/{employee_record.pk}",
                    "/employee_record/summary/[PK of EmployeeRecord]",
                )
            ],
        )
        assert html == snapshot()

    def test_post_hired_with_employee_record_another_siae_on_the_same_convention(self, client, snapshot):
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="Eliott", last_name="Emery")
        approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00003")
        # Add a dummy application so that the job seeker is in the
        # pool of applicants to `self.siae`.
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=self.siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
        )
        other_siae = CompanyFactory(
            kind=self.siae.kind,
            name="L'Autre",
            convention=self.siae.convention,
            source=CompanySource.USER_CREATED,
        )
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=other_siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            hiring_start_at=datetime.date(2025, 2, 14),
        )
        EmployeeRecordFactory(job_application=job_application)

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_OTHER_COMPANY
        assert self._extract_html_section(response) == snapshot()

    def test_post_hired_with_employee_record_another_siae_same_siret_another_convention(self, client):
        self.setUp(client)
        job_seeker = JobSeekerFactory(first_name="Eliott", last_name="Emery")
        approval = ApprovalFactory(user=job_seeker, number="XXXXXXX00003")
        # Add a dummy application so that the job seeker is in the
        # pool of applicants to `self.siae`.
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=self.siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
        )
        other_siae = CompanyFactory(
            siret=self.siae.siret,
            kind="ETTI",  # different from self.siae.kind
            with_convention=True,
        )
        assert other_siae.kind != self.siae.kind
        assert other_siae.convention_id != self.siae.convention_id
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=other_siae,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            hiring_start_at=datetime.date(2025, 2, 14),
        )
        EmployeeRecordFactory(job_application=job_application)

        response = client.post(self.url, data={"employee": job_seeker.pk})
        assert self._extract_case(response) == MissingEmployeeCase.EXISTING_EMPLOYEE_RECORD_OTHER_COMPANY
