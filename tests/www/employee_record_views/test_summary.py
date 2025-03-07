import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.utils.templatetags.format_filters import format_approval_number, format_siret
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory, EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory


class TestSummaryEmployeeRecords:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_company=self.company)
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
            response, f"<li>À : {profile.birth_place} ({profile.birth_place.department_code})</li>", count=1
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
        assertContains(response, "Création : <b>RIAE_FS_20210410130000")

        EmployeeRecordUpdateNotificationFactory(
            employee_record=self.employee_record, asp_batch_file="RIAE_FS_20210510130000.json"
        )
        response = client.get(self.url)
        assertContains(response, HORODATAGE)
        assertContains(response, "Création : <b>RIAE_FS_20210410130000")
        assertContains(response, "Modification : <b>RIAE_FS_20210510130000")

    def test_technical_infos(self, client):
        client.force_login(self.user)
        response = client.get(self.url)

        assertContains(response, format_approval_number(self.employee_record.approval_number))
        assertContains(response, format_siret(self.employee_record.siret))
        assertContains(response, self.employee_record.asp_measure)
