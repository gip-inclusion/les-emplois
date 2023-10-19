from django.urls import reverse

from tests.companies.factories import SiaeWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory, EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from tests.utils.test import TestCase


class SummaryEmployeeRecordsTest(TestCase):
    def setUp(self):
        super().setUp()
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.siae.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.siae)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:summary", args=(self.employee_record.id,))

    def test_access_granted(self):
        # Must have access
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_check_job_seeker_infos(self):
        # Must have access
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        profile = self.job_application.job_seeker.jobseeker_profile
        self.assertContains(
            response, f"<li>À : {profile.birth_place} ({profile.birth_place.department_code})</li>", count=1
        )

    def test_asp_batch_file_infos(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Horodatage ASP")

        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent("RIAE_FS_20210410130000.json", 1, None)

        response = self.client.get(self.url)
        self.assertContains(response, "Horodatage ASP")
        self.assertContains(response, "Création : <b>RIAE_FS_20210410130000")

        EmployeeRecordUpdateNotificationFactory(
            employee_record=self.employee_record, asp_batch_file="RIAE_FS_20210510130000.json"
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Horodatage ASP")
        self.assertContains(response, "Création : <b>RIAE_FS_20210410130000")
        self.assertContains(response, "Modification : <b>RIAE_FS_20210510130000")
