from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD


class CreateEmployeeRecordStep1Test(TestCase):
    fixtures = [
        "test_INSEE_communes.json",
        "test_INSEE_country.json",
    ]

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
        self.url = reverse("employee_record_views:create", args=(self.job_application.id,))

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

    def test_title(self):
        """
        Job seeker / employee must have a title
        """
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.client.get(self.url)

        data = {
            "first_name": self.job_seeker.first_name,
            "last_name": self.job_seeker.last_name,
            "birthdate": self.job_seeker.birthdate.strftime("%d/%m/%Y"),
            "birth_country": 91,
            "insee_commune_code": 62152,
        }

        response = self.client.post(self.url, data=data)
        self.assertEqual(200, response.status_code)

        data["title"] = "MME"
        response = self.client.post(self.url, data=data)

        self.assertEqual(302, response.status_code)

    def test_birthplace(self):
        """
        If birth country is France, a commune must be entered
        """
        # Validation is done by the model
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.client.get(self.url)

        data = {
            "title": "M",
            "first_name": self.job_seeker.first_name,
            "last_name": self.job_seeker.last_name,
            "birthdate": self.job_seeker.birthdate.strftime("%d/%m/%Y"),
        }

        # Missing birth country
        response = self.client.post(self.url, data=data)
        self.assertEqual(200, response.status_code)

        # France as birth country without commune
        data["birth_country"] = 91  # France
        data["insee_commune_code"] = ""
        response = self.client.post(self.url, data=data)

        self.assertEqual(200, response.status_code)

        # Set a "random" commune in France
        data["insee_commune_code"] = 62152
        response = self.client.post(self.url, data=data)
        self.assertEqual(302, response.status_code)

        # Set a country different from France
        data["insee_commune_code"] = ""
        data["birth_country"] = 92  # Denmark
        response = self.client.post(self.url, data=data)

        self.assertEqual(302, response.status_code)
