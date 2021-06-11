from unittest import mock

from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import (
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
)
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerWithMockedAddressFactory
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


class AbstractCreateEmployeeRecordTest(TestCase):
    def setUp(self):
        self.siae = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        self.siae_without_perms = SiaeWithMembershipAndJobsFactory(
            kind="EI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.siae_bad_kind = SiaeWithMembershipAndJobsFactory(
            kind="EITI", name="A-Team", membership__user__first_name="Barracus"
        )

        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.user_siae_bad_kind = self.siae_bad_kind.members.get(first_name="Barracus")

        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
        )
        self.job_seeker = self.job_application.job_seeker

    def login_response(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        return self.client.get(self.url)

    def pass_step_1(self):
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        url = reverse("employee_record_views:create", args=(self.job_application.id,))
        response = self.client.post(url, data=get_sample_form_data_step_1(self.job_seeker))

        self.assertEqual(302, response.status_code)
        self.assertTrue(self.job_seeker.has_jobseeker_profile)

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def pass_step_2(self, _mock):
        self.pass_step_1()
        url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        self.client.get(url)

        self.assertTrue(self.job_seeker.jobseeker_profile.hexa_address_filled)

        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

    # Perform check permissions for each step

    def test_access_denied_bad_permissions(self):
        # Must not have access
        self.client.login(username=self.user_without_perms.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_access_denied_bad_siae_kind(self):
        # SIAE can't use employee record (not the correct kind)
        self.client.login(username=self.user_siae_bad_kind.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)


class CreateEmployeeRecordStep1Test(AbstractCreateEmployeeRecordTest):
    """
    Create employee record step 1:

    Employee details form: title and birth place
    """

    fixtures = [
        "test_INSEE_communes.json",
        "test_INSEE_country.json",
    ]

    def setUp(self):
        super().setUp()
        self.url = reverse("employee_record_views:create", args=(self.job_application.id,))

    def test_access_granted(self):
        # Must have access
        self.client.login(username=self.user.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_title(self):
        # Job seeker / employee must have a title

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
        # If birth country is France, a commune (INSEE) is mandatory
        # otherwise, only a country is mandatory

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


class CreateEmployeeRecordStep2Test(AbstractCreateEmployeeRecordTest):
    """
    Create employee record step 2:

    Test employee (HEXA) address
    """

    fixtures = [
        "test_INSEE_communes.json",
        "test_INSEE_country.json",
    ]

    def setUp(self):
        super().setUp()

        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae, job_seeker=JobSeekerWithMockedAddressFactory()
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))

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
    def test_valid_address(self, _mock):
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

    def test_update_with_bad_address(self):
        # If HEXA address is valid, user can still change it
        # but it must be a valid one, otherwise the previus address is discarded

        # Pass step 1
        self.pass_step_1()

        # Set an invalid address
        data = {
            "address_line_1": "",
            "post_code": "",
            "city": "",
        }

        # And update it
        response = self.client.post(self.url, data=data)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.job_seeker.jobseeker_profile.hexa_address_filled)


class CreateEmployeeRecordStep3Test(AbstractCreateEmployeeRecordTest):
    """
    Create employee record step 2:

    Employee situation and social allowances
    """

    fixtures = [
        "test_INSEE_communes.json",
        "test_INSEE_country.json",
    ]

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae, job_seeker=JobSeekerWithMockedAddressFactory()
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))

        self.pass_step_2()

        self.profile = self.job_seeker.jobseeker_profile

    # Most of coherence test are done in the model

    # "Basic" folds : check invalidation of hidden fields

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_fold_pole_emploi(self, _mock):
        # Test behaviour of Pôle Emploi related fields
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must be pre-checked if job seeker has a Pôle emploi ID
        self.assertTrue(form.initial["pole_emploi"])

        # Fill other mandatory field from fold
        # POST will fail because if education_level is not filled
        data = {
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi_since": "01",
            "education_level": "00",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(302, response.status_code)

        self.profile.refresh_from_db()

        self.assertEqual("01", self.profile.pole_emploi_since)

    def test_fold_unemployed(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        self.assertFalse(form.initial["unemployed"])

        # Fill other mandatory field from fold
        data = {
            "unemployed": True,
            "unemployed_since": "02",
            "education_level": "00",
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(302, response.status_code)

        self.profile.refresh_from_db()

        self.assertEqual("02", self.profile.unemployed_since)

    def test_fold_rsa(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        self.assertFalse(form.initial["rsa_allocation"])

        # Fill other mandatory field from fold
        data = {
            "rsa_allocation": True,
            "rsa_allocation_since": "02",
            "rsa_markup": "OUI-M",
            "education_level": "00",
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(302, response.status_code)

        self.profile.refresh_from_db()

        self.assertEqual("OUI-M", self.profile.has_rsa_allocation)

    def test_fold_ass(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        self.assertFalse(form.initial["ass_allocation"])

        # Fill other mandatory field from fold
        data = {
            "ass_allocation": True,
            "ass_allocation_since": "03",
            "education_level": "00",
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(302, response.status_code)

        self.profile.refresh_from_db()

        self.assertEqual("03", self.profile.ass_allocation_since)

    def test_fold_ata(self):
        pass
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        self.assertFalse(form.initial["ata_allocation"])

        # Fill other mandatory field from fold
        data = {
            "ata_allocation": True,
            "ata_allocation_since": "04",
            "education_level": "00",
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertEqual(302, response.status_code)

        self.profile.refresh_from_db()

        self.assertEqual("04", self.profile.ata_allocation_since)


# Tip: do no launch this test as standalone (unittest.skip does not work as expected)
del AbstractCreateEmployeeRecordTest
