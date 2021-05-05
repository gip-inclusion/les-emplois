from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD


class ListEmployeeRecordsTest(TestCase):
    def setUp(self):
        self.siae = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        self.siae_without_perms = SiaeWithMembershipAndJobsFactory(
            kind="EITI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.job_application = JobApplicationWithApprovalFactory(
            to_siae=self.siae,
        )
        self.url = reverse("employee_record_views:list")

    def test_permissions(self):
        """
        Non-eligible SIAE should not be able to access this list
        """
        self.client.login(username=self.user_without_perms.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_new_employee_records(self):
        """
        Check if new employee records / job applications are displayed in the list
        """
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        self.assertContains(response, self.user.get_full_name())

    # To be completed with other status during UI part 2 ...
