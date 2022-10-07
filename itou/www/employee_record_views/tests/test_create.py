from unittest import mock

from django.urls import reverse

from itou.asp.models import Commune, Country
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.employee_record.tests.common import EmployeeRecordFixtureTest
from itou.job_applications.factories import (
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithJobSeekerProfileFactory,
)
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import JobSeekerWithMockedAddressFactory
from itou.utils.mocks.address_format import get_random_insee_code, mock_get_geocoding_data
from itou.utils.widgets import DuetDatePickerWidget


# Helper functions
def get_sample_form_data(user):
    return {
        "title": "M",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "birthdate": user.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "birth_country": 91,  # France
        "insee_commune_code": get_random_insee_code(),
    }


class AbstractCreateEmployeeRecordTest(EmployeeRecordFixtureTest):
    def setUp(self):
        self.siae = SiaeWithMembershipAndJobsFactory(
            name="Evil Corp.", membership__user__first_name="Elliot", kind="EI"
        )
        self.siae_without_perms = SiaeWithMembershipAndJobsFactory(
            kind="EI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.siae_bad_kind = SiaeWithMembershipAndJobsFactory(
            kind="EA", name="A-Team", membership__user__first_name="Barracus"
        )

        self.user = self.siae.members.get(first_name="Elliot")
        self.user_without_perms = self.siae_without_perms.members.get(first_name="Hannibal")
        self.user_siae_bad_kind = self.siae_bad_kind.members.get(first_name="Barracus")

        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker_with_address=True,
        )
        self.job_seeker = self.job_application.job_seeker

    def login_response(self):
        self.client.force_login(self.user)
        return self.client.get(self.url)

    # Bypass each step with minimum viable data

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def pass_step_1(self, _mock):
        self.client.force_login(self.user)
        url = reverse("employee_record_views:create", args=(self.job_application.id,))
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        data = get_sample_form_data((self.job_seeker))
        response = self.client.post(url, data=data)

        self.assertRedirects(response, target_url)

        self.assertTrue(self.job_seeker.has_jobseeker_profile)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
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

    def pass_step_3(self):
        self.pass_step_2()
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        self.client.get(url)

        data = {
            "education_level": "00",
            # Factory user is registed to Pôle emploi: all fields must be filled
            "pole_emploi_since": "02",
            # "pole_emploi_id": "1234567X",
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)

    def pass_step_4(self):
        self.pass_step_3()
        url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))
        self.client.get(url)

        # Do not use financial annex number om ModelChoiceField: must pass an ID !
        data = {"financial_annex": self.siae.convention.financial_annexes.first().id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 302)

    # Perform check permissions for each step

    def test_access_denied_bad_permissions(self):
        # Must not have access
        self.client.force_login(self.user_without_perms)

        response = self.client.get(self.url)
        # Changed to 404
        self.assertEqual(response.status_code, 404)

    def test_access_denied_bad_siae_kind(self):
        # SIAE can't use employee record (not the correct kind)
        self.client.force_login(self.user_siae_bad_kind)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)


class CreateEmployeeRecordStep1Test(AbstractCreateEmployeeRecordTest):
    """
    Employee details form: title and birth place
    """

    def setUp(self):
        super().setUp()
        self.url = reverse("employee_record_views:create", args=(self.job_application.pk,))
        self.target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

    def test_access_granted(self):
        # Must have access
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_hiring_end_at_date_in_header(self):

        hiring_end_at = self.job_application.hiring_end_at

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Fin du contrat : <b>{hiring_end_at.strftime('%e').lstrip()}")

    def test_no_hiring_end_at_in_header(self):
        self.job_application.hiring_end_at = None
        self.job_application.save()

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fin du contrat : <b>Non renseigné")

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_title(self, _mock):
        # Job seeker / employee must have a title

        self.client.force_login(self.user)
        self.client.get(self.url)

        data = get_sample_form_data(self.job_seeker)
        data.pop("title")

        response = self.client.post(self.url, data=data)
        self.assertEqual(200, response.status_code)

        data["title"] = "MME"
        response = self.client.post(self.url, data=data)

        self.assertRedirects(response, self.target_url)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_bad_birthplace(self, _mock):
        # If birth country is France, a commune (INSEE) is mandatory
        # otherwise, only a country is mandatory

        # Validation is done by the model
        self.client.force_login(self.user)
        self.client.get(self.url)

        data = get_sample_form_data(self.job_seeker)
        data.pop("birth_country")

        # Missing birth country
        response = self.client.post(self.url, data=data)
        self.assertEqual(200, response.status_code)

        # France as birth country without commune
        data["birth_country"] = 91  # France
        data["insee_commune_code"] = ""
        response = self.client.post(self.url, data=data)

        self.assertEqual(200, response.status_code)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_good_birthplace(self, _mock):
        self.client.force_login(self.user)
        self.client.get(self.url)

        data = get_sample_form_data(self.job_seeker)
        data["insee_commune_code"] = get_random_insee_code()
        response = self.client.post(self.url, data=data)

        # Redirects must go to step 2
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

        # Default test values are ok
        self.assertRedirects(response, target_url)

        # Set a country different from France
        data["insee_commune_code"] = ""
        data["birth_country"] = 92  # Denmark
        response = self.client.post(self.url, data=data)

        self.assertRedirects(response, target_url)


class CreateEmployeeRecordStep2Test(AbstractCreateEmployeeRecordTest):
    """
    Test employee (HEXA) address
    """

    def setUp(self):
        super().setUp()

        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(
            to_siae=self.siae,
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

    def test_access_granted(self):
        # Pass step 1
        self.pass_step_1()

        # Must pass
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_valid_address(self, _mock):
        # Most HEXA address tests are done in user profile

        # Pass step 1
        self.pass_step_1()

        # Accept address provided by mock and pass to step 3
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.pk,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_invalid_address(self):
        # Was using a mock (or not using it actually), but a proper factory will do
        self.job_application = JobApplicationWithJobSeekerProfileFactory(
            to_siae=self.siae,
            job_seeker_with_address=True,
        )
        self.job_seeker = self.job_application.job_seeker

        # Pass step 1
        self.pass_step_1()

        self.assertFalse(self.job_seeker.jobseeker_profile.hexa_address_filled)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        # Try to force the way
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.pk,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_update_with_bad_address(self):
        # If HEXA address is valid, user can still change it
        # but it must be a valid one, otherwise the previous address is discarded
        self.job_application = JobApplicationWithJobSeekerProfileFactory(
            to_siae=self.siae,
            job_seeker_with_address=True,
        )
        self.job_seeker = self.job_application.job_seeker

        # Pass step 1
        self.pass_step_1()

        # Set an invalid address
        data = {
            "hexa_lane_name": "",
            "hexa_lane_type": "",
            "hexa_post_code": "xxx",
            "insee_commune_code": "xxx",
        }

        # And update it
        response = self.client.post(self.url, data=data)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.job_seeker.jobseeker_profile.hexa_address_filled)

    def test_address_updated_by_user(self):
        # User can now update the geolocated address if invalid

        # Pass step 1
        self.pass_step_1()

        test_data = {
            "hexa_lane_number": "15",
            "hexa_std_extension": "B",
            "hexa_lane_type": "RUE",
            "hexa_lane_name": "des colonies",
            "hexa_additional_address": "Bat A",
            "hexa_post_code": "67000",
            "insee_commune": "STRASBOURG",
            "insee_commune_code": "67482",
        }

        data = test_data
        response = self.client.post(self.url, data=data)
        # This data set should pass
        self.assertEqual(response.status_code, 302)

        # Check form validators

        # Lane number :
        data = test_data

        # Can't use extension without number
        data["hexa_lane_number"] = ""
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # Can't use anything else than up to 5 digits
        data["hexa_lane_number"] = "a"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        data["hexa_lane_number"] = "123456"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # Post code :
        data = test_data

        # 5 digits exactly
        data["hexa_post_code"] = "123456"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        data["hexa_post_code"] = "1234"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        data["hexa_lane_number"] = "1234a"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # Coherence with INSEE code
        data["hexa_lane_number"] = "12345"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # Lane name and additional address
        data = test_data

        # No special characters
        data["hexa_lane_name"] = "des colons !"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # 32 chars max
        data["hexa_lane_name"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        data = test_data
        data["hexa_additional_address"] = "Bat a !"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)

        # 32 chars max
        data["hexa_additional_address"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = self.client.post(self.url, data=data)
        self.assertEqual(response.status_code, 200)


class CreateEmployeeRecordStep3Test(AbstractCreateEmployeeRecordTest):
    """
    Employee situation and social allowances
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker=JobSeekerWithMockedAddressFactory(),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        self.target_url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))

        self.pass_step_2()

        self.profile = self.job_seeker.jobseeker_profile

    # Most of coherence test are done in the model

    # "Basic" folds : check invalidation of hidden fields

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
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

        self.assertRedirects(response, self.target_url)

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
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

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
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

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
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

        self.profile.refresh_from_db()

        self.assertEqual("03", self.profile.ass_allocation_since)

    def test_fail_step_3(self):
        # If anything goes wrong during employee record creation,
        # catch error / exceptions and display a message
        self.pass_step_2()
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        self.client.get(url)

        # Correct data :
        data = {
            "education_level": "00",
            # Factory user is registed to Pôle emploi: all fields must be filled
            "pole_emploi_since": "02",
            # "pole_emploi_id": "1234567X",
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "pole_emploi": True,
        }

        # but incorrect context :
        # create another employee record with similar features
        dup_job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker=self.job_seeker,
            approval=self.job_application.approval,
        )
        # Get a test commune from fixtures
        commune = Commune.by_insee_code(get_random_insee_code())

        dup_job_application.job_seeker.jobseeker_profile.education_level = "00"
        dup_job_application.job_seeker.jobseeker_profile.commune = commune
        dup_job_application.job_seeker.birth_place = commune

        dup_job_application.job_seeker.birth_country = Country.objects.filter(code=Country._CODE_FRANCE).first()
        dup_job_application.save()

        employee_record = EmployeeRecord.from_job_application(dup_job_application)
        employee_record.save()

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Il est impossible de créer cette fiche salarié pour la raison suivante",
        )


class CreateEmployeeRecordStep4Test(AbstractCreateEmployeeRecordTest):
    """
    Selection of a financial annex
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker=JobSeekerWithMockedAddressFactory(),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))

        self.pass_step_3()

    # Only permissions and basic access here


class CreateEmployeeRecordStep5Test(AbstractCreateEmployeeRecordTest):
    """
    Check summary of employee record and validation
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker=JobSeekerWithMockedAddressFactory(),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_5", args=(self.job_application.id,))

        self.pass_step_4()

    def test_employee_record_status(self):
        # Employee record should now be ready to send (READY)

        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        self.assertEqual(employee_record.status, Status.NEW)

        # Validation of create process
        self.client.post(self.url)

        employee_record.refresh_from_db()
        self.assertEqual(employee_record.status, Status.READY)


class UpdateRejectedEmployeeRecordTest(AbstractCreateEmployeeRecordTest):
    """
    Check if update and resubmission is possible after employee record rejection
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_siae=self.siae,
            job_seeker=JobSeekerWithMockedAddressFactory(),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_5", args=(self.job_application.id,))

        self.pass_step_4()

        self.client.post(self.url)

        # Reject employee record
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)

        # Must change status twice (contrained lifecycle)
        employee_record.update_as_sent("fooFileName.json", 1)
        self.assertEqual(employee_record.status, Status.SENT)

        employee_record.update_as_rejected("0001", "Error message")

        self.assertEqual(employee_record.status, Status.REJECTED)

        self.employee_record = employee_record

    def test_submit_after_rejection(self):
        # Validation of update process after rejection by ASP
        self.pass_step_4()

        self.client.post(self.url)

        self.employee_record.refresh_from_db()
        self.assertEqual(self.employee_record.status, Status.READY)

    # Simpler to test summary access from here

    def test_summary(self):
        # Check if summary is accessible
        self.pass_step_4()
        self.client.post(self.url)
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)

        self.url = reverse("employee_record_views:summary", args=(employee_record.id,))
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)


# Tip: do no launch this test as standalone (unittest.skip does not work as expected)
del AbstractCreateEmployeeRecordTest
