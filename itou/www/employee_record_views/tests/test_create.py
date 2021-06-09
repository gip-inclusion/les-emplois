from unittest import mock

from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD
from itou.utils.mocks.address_format import mock_get_geocoding_data


# Helper functions
def get_sample_form_data_step_1(user):
    return {
        "title": "M",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "birthdate": user.birthdate.strftime("%d/%m/%Y"),
        "birth_country": 91,
        "insee_commune_code": 62152,
    }


class CreateEmployeeRecordStep1Test(TestCase):
    """
    Create employee record step 1:
    Test employee details form: title and birth place
    """

    fixtures = [
        "test_INSEE_communes.json",
        "test_INSEE_country.json",
    ]

    def setUp(self):
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
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

        data = get_sample_form_data_step_1(self.job_seeker)
        data.pop("title")

        response = self.client.post(self.url, data=data)
        self.assertEqual(200, response.status_code)

        data["title"] = "MME"
        response = self.client.post(self.url, data=data)

        self.assertEqual(302, response.status_code)

    def test_birthplace(self):
        """
        If birth country is France, a commune (INSEE) is mandatory
        otherwise, only a country is mandatory
        """
        # Validation is done by the model
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        self.client.get(self.url)

        data = get_sample_form_data_step_1(self.job_seeker)
        data.pop("birth_country")

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


class CreateEmployeeRecordStep2Test(TestCase):
    """
    Create employee record step 2:
    Test employee address
    """

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
            kind="EI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))

    def pass_step_1(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        url = reverse("employee_record_views:create", args=(self.job_application.id,))
        response = self.client.post(url, data=get_sample_form_data_step_1(self.job_seeker))

        self.assertEqual(302, response.status_code)
        self.assertTrue(self.job_seeker.has_jobseeker_profile)

    def test_access_denied(self):
        # Must not have access
        self.client.login(username=self.user_without_perms.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_direct_access_denied(self):
        # Even if allowed, url of step must not be accessible without
        # a user profile (bypassing step 1)
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_access_granted(self):
        # Pass step 1
        self.pass_step_1()

        # Must pass
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def _test_valid_address(self, _mock):
        # Most HEXA address tests are done in user profile

        # Pass step 1
        self.pass_step_1()

        # Accept address provided by mock and pass to step 3
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_invalid_address(self):
        # No mock here, address must be invalid

        # Pass step 1
        self.pass_step_1()

        self.assertFalse(self.job_seeker.jobseeker_profile.hexa_address_filled)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        # No option to continue to next step
        self.assertNotContains(response, "Continuer")
        self.assertFalse(self.job_seeker.jobseeker_profile.hexa_address_filled)

        # Try to force the way
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
