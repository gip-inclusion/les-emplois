import pgtrigger
import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains

from itou.employee_record.enums import Status
from itou.utils.templatetags.format_filters import format_approval_number, format_siret
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory, EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


class TestSummaryEmployeeRecords:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(
            to_company=self.company, job_seeker__first_name="Lauren", job_seeker__last_name="Mata"
        )
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:summary", args=(self.employee_record.id,))

    def test_access_granted(self, client):
        # Must have access
        client.force_login(self.user)
        response = client.get(self.url)
        assert response.status_code == 200

    def test_check_job_seeker_infos(self, client):
        # Must have access
        client.force_login(self.user)
        response = client.get(self.url)
        profile = self.job_application.job_seeker.jobseeker_profile
        assertContains(
            response,
            f"""
            <li>
            <small>Lieu de naissance</small>
            <strong>{profile.birth_place} ({profile.birth_place.department_code})</strong>
            </li>
            """,
            html=True,
        )

    def test_asp_batch_file_infos(self, client):
        HORODATAGE = "Horodatage ASP"
        client.force_login(self.user)
        response = client.get(self.url)
        assertNotContains(response, HORODATAGE)

        self.employee_record.ready()
        self.employee_record.wait_for_asp_response(file="RIAE_FS_20210410130000.json", line_number=1, archive=None)

        response = client.get(self.url)
        assertContains(response, HORODATAGE)
        assertContains(
            response,
            """
            <li>
            <small>Création</small>
            <strong>RIAE_FS_20210410130000</strong>
            </li>
            """,
            html=True,
        )

        EmployeeRecordUpdateNotificationFactory(
            employee_record=self.employee_record, asp_batch_file="RIAE_FS_20210510130000.json"
        )
        response = client.get(self.url)
        assertContains(response, HORODATAGE)
        assertContains(
            response,
            """
            <li>
            <small>Création</small>
            <strong>RIAE_FS_20210410130000</strong>
            </li>
            <li>
            <small>Modification</small>
            <strong>RIAE_FS_20210510130000</strong>
            </li>
            """,
            html=True,
        )

    def test_technical_infos(self, client):
        client.force_login(self.user)
        response = client.get(self.url)

        assertContains(response, format_approval_number(self.employee_record.approval_number))
        assertContains(response, format_siret(self.employee_record.siret))
        assertContains(response, self.employee_record.asp_measure)

    def get_title_section_soup(self, response):
        return parse_response_to_soup(
            response,
            selector=".s-title-02__col",
            replace_in_attr=[
                (
                    "href",
                    f"/employee_record/reactivate/{self.employee_record.pk}",
                    "/employee_record/reactivate/[Pk of EmployeeRecord]",
                ),
                (
                    "href",
                    f"/employee_record/create/{self.employee_record.job_application_id}",
                    "/employee_record/create/[Pk of JobApplication]",
                ),
                (
                    "action",
                    f"/employee_record/create_step_5/{self.employee_record.job_application_id}",
                    "/employee_record/create_step_5/[Pk of JobApplication]",
                ),
                (
                    "href",
                    f"/employee_record/disable/{self.employee_record.pk}",
                    "/employee_record/disable/[Pk of EmployeeRecord]",
                ),
                (
                    "id",
                    f"sendBackRecordDropDown-{self.employee_record.pk}",
                    "sendBackRecordDropDown-[Pk of EmployeeRecord]",
                ),
                (
                    "aria-controls",
                    f"sendBackRecordDropDown-{self.employee_record.pk}",
                    "sendBackRecordDropDown-[Pk of EmployeeRecord]",
                ),
            ],
        )

    @freeze_time("2025-04-29 11:11:11")
    @pytest.mark.parametrize(
        "status",
        [
            Status.NEW,
            Status.READY,
            Status.SENT,
            Status.REJECTED,
            Status.DISABLED,
            Status.ARCHIVED,
            Status.PROCESSED,
        ],
    )
    def test_action_bar(self, client, status, snapshot):
        self.employee_record.status = status
        self.employee_record.save()

        client.force_login(self.user)
        response = client.get(self.url)
        title_section_soup = self.get_title_section_soup(response)

        assert pretty_indented(title_section_soup) == snapshot

    @freeze_time("2025-04-29 11:11:11")
    @pytest.mark.parametrize(
        "status",
        [
            Status.READY,
            Status.PROCESSED,
        ],
    )
    @pgtrigger.ignore("companies.Company:company_fields_history")
    def test_action_bar_with_changed_siret(self, client, status, snapshot):
        self.employee_record.status = status
        self.company.siret = "10000000000001"
        self.employee_record.siret = "10000000000002"
        self.company.save()
        self.employee_record.save()

        client.force_login(self.user)
        response = client.get(self.url)
        title_section_soup = self.get_title_section_soup(response)

        assert pretty_indented(title_section_soup) == snapshot
