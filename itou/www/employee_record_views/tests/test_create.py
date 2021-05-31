from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD


class CreateEmployeeRecordStep1Test(TestCase):
    def setUp(self):
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(
            name="Evil Corp.", membership__user__first_name="Elliot", membership__user__is_superuser=True
        )
        self.siae_without_perms = SiaeWithMembershipAndJobsFactory(
            kind="EITI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create", args=(self.job_application.id))

    def test_access_granted(self):
        # Must not have access
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_access_denied(self):
        # Must have access
        self.client.login(username=self.user_without_perms.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_birth_country(self):
        # Validation is done by the model
        self.client.login(username=self.user_without_perms.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        # Set a random commune
        data = {}

        # Set a country different from France

        #
