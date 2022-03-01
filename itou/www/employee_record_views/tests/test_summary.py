from django.test import TestCase
from django.urls import reverse

from itou.employee_record.factories import EmployeeRecordWithProfileFactory
from itou.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD


class SummaryEmployeeRecordsTest(TestCase):
    def setUp(self):
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(
            name="Wanna Corp.", membership__user__first_name="Billy", membership__user__is_superuser=True
        )
        self.user = self.siae.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.siae)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:summary", args=(self.employee_record.id,))

    def test_access_granted(self):
        # Must have access
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_hiring_end_at_date_in_header(self):
        hiring_end_at = self.job_application.hiring_end_at
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Fin du contrat : <b>{hiring_end_at.strftime('%d')}")

    def test_no_hiring_end_at_in_header(self):
        self.job_application.hiring_end_at = None
        self.job_application.save()
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fin du contrat : <b>Non renseigné")
