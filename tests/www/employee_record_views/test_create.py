import datetime
from unittest import mock

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from itou.asp.models import Commune
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from itou.users.enums import LackOfNIRReason
from itou.utils.mocks.address_format import mock_get_geocoding_data
from itou.utils.widgets import DuetDatePickerWidget
from tests.asp.factories import CommuneFactory, CountryFranceFactory, CountryOutsideEuropeFactory
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from tests.users.factories import JobSeekerWithAddressFactory
from tests.utils.test import TestCase


# Helper functions
def _get_user_form_data(user):
    form_data = {
        "title": "M",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "birthdate": user.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
    }
    if user.jobseeker_profile.birth_country:
        form_data["birth_country"] = user.jobseeker_profile.birth_country_id
    if user.jobseeker_profile.birth_place:
        form_data["birth_place"] = user.jobseeker_profile.birth_place_id
    return form_data


class AbstractCreateEmployeeRecordTest(TestCase):
    def setUp(self):
        super().setUp()
        self.company = CompanyWithMembershipAndJobsFactory(
            name="Evil Corp.", membership__user__first_name="Elliot", kind="EI"
        )
        self.company_without_perms = CompanyWithMembershipAndJobsFactory(
            kind="EI", name="A-Team", membership__user__first_name="Hannibal"
        )
        self.company_bad_kind = CompanyWithMembershipAndJobsFactory(
            kind="EA", name="A-Team", membership__user__first_name="Barracus"
        )

        self.user = self.company.members.get(first_name="Elliot")
        self.user_without_perms = self.company_without_perms.members.get(first_name="Hannibal")
        self.user_siae_bad_kind = self.company_bad_kind.members.get(first_name="Barracus")

        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker_with_address=True,
            job_seeker__born_in_france=True,
        )

        self.job_seeker = self.job_application.job_seeker

    # Bypass each step with minimum viable data

    def pass_step_1(self):
        self.client.force_login(self.user)
        url = reverse("employee_record_views:create", args=(self.job_application.id,))
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        data = _get_user_form_data(self.job_seeker)
        response = self.client.post(url, data=data)

        self.assertRedirects(response, target_url)

        return response

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def pass_step_2(self, _mock):
        self.pass_step_1()
        url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        self.client.get(url)

        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.hexa_address_filled

        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        response = self.client.get(url)

        assert response.status_code == 200

    def pass_step_3(self):
        self.pass_step_2()
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        self.client.get(url)

        data = {
            "education_level": "00",
            # Factory user is registed to Pôle emploi: all fields must be filled
            "pole_emploi_since": "02",
            # "pole_emploi_id": "1234567X",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi": True,
        }
        response = self.client.post(url, data)

        assert response.status_code == 302

    def pass_step_4(self):
        self.pass_step_3()
        url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))
        self.client.get(url)

        # Do not use financial annex number om ModelChoiceField: must pass an ID !
        data = {"financial_annex": self.company.convention.financial_annexes.first().id}
        response = self.client.post(url, data)

        assert response.status_code == 302

    # Perform check permissions for each step

    def test_access_denied_bad_permissions(self):
        # Must not have access
        self.client.force_login(self.user_without_perms)

        response = self.client.get(self.url)
        # Changed to 404
        assert response.status_code == 404

    def test_access_denied_bad_siae_kind(self):
        # SIAE can't use employee record (not the correct kind)
        self.client.force_login(self.user_siae_bad_kind)

        response = self.client.get(self.url)

        assert response.status_code == 403

    def test_access_denied_nir_associated_to_other(self):
        self.job_seeker = self.job_application.job_seeker
        self.job_seeker.nir = ""
        self.job_seeker.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        self.job_seeker.save(update_fields=("nir", "lack_of_nir_reason"))

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertContains(response, "régulariser le numéro de sécurité sociale", status_code=403)


class CreateEmployeeRecordStep1Test(AbstractCreateEmployeeRecordTest):
    """
    Employee details form: title and birth place
    """

    def setUp(self):
        super().setUp()
        self.job_seeker = JobSeekerWithAddressFactory.build(born_in_france=True)

        self.url = reverse("employee_record_views:create", args=(self.job_application.pk,))
        self.target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

    def test_access_granted(self):
        # Must have access
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        assert response.status_code == 200

    def test_title(self):
        # Job seeker / employee must have a title

        self.client.force_login(self.user)
        self.client.get(self.url)

        data = _get_user_form_data(self.job_seeker)
        data.pop("title")

        response = self.client.post(self.url, data=data)
        assert 200 == response.status_code

        data["title"] = "MME"
        response = self.client.post(self.url, data=data)

        self.assertRedirects(response, self.target_url)

    def test_bad_birthplace(self):
        # If birth country is France, a commune (INSEE) is mandatory
        # otherwise, only a country is mandatory

        # Validation is done by the model
        self.client.force_login(self.user)
        self.client.get(self.url)

        data = _get_user_form_data(self.job_seeker)
        data.pop("birth_country")

        # Missing birth country
        response = self.client.post(self.url, data=data)
        assert 200 == response.status_code

        # France as birth country without commune
        data["birth_country"] = CountryFranceFactory().pk
        data.pop("birth_place")
        response = self.client.post(self.url, data=data)

        assert 200 == response.status_code

    def test_birthplace_in_france(self):
        self.client.force_login(self.user)
        self.client.get(self.url)

        data = _get_user_form_data(self.job_seeker)
        data["birth_place"] = CommuneFactory().pk
        response = self.client.post(self.url, data=data)

        # Redirects must go to step 2
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

        # Default test values are ok
        self.assertRedirects(response, target_url)

    def test_birthplace_outside_of_france(self):
        self.client.force_login(self.user)
        self.client.get(self.url)

        # Set a country different from France
        data = _get_user_form_data(self.job_seeker)
        data.pop("birth_place")
        data["birth_country"] = CountryOutsideEuropeFactory().pk

        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))
        response = self.client.post(self.url, data=data)

        self.assertRedirects(response, target_url)

    def test_pass_step_1_without_geolocated_address(self):
        # Do not mess with job seeker profile and geolocation at step 1
        # just check user model info

        self.client.force_login(self.user)
        self.client.get(self.url)

        # No geoloc mock used, basic factory with:
        # - simple / fake address
        # - birth place and country
        data = _get_user_form_data(JobSeekerWithAddressFactory.build(born_in_france=True))
        response = self.client.post(self.url, data=data)

        # Redirects must go to step 2
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

        self.assertRedirects(response, target_url)


class CreateEmployeeRecordStep2Test(AbstractCreateEmployeeRecordTest):

    NO_ADDRESS_FILLED_IN = "Aucune adresse n'a été saisie sur les emplois de l'inclusion !"
    ADDRESS_COULD_NOT_BE_AUTO_CHECKED = "L'adresse du salarié n'a pu être vérifiée automatiquement."

    def setUp(self):
        super().setUp()
        self.url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))
        self.client.force_login(self.user)

    def test_access_granted(self):
        self.pass_step_1()
        response = self.client.get(self.url)

        assert response.status_code == 200

    def test_job_seeker_without_address(self):
        # Job seeker has no address filled (which should not happen without admin operation)
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(to_company=self.company)

        response = self.client.get(self.url)
        url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))
        response = self.client.get(url)

        self.assertContains(response, self.NO_ADDRESS_FILLED_IN)
        self.assertContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_job_seeker_address_geolocated(self, _mock):
        # Accept geolocated address provided by mock and pass to step 3
        response = self.client.get(self.url)
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.pk,))
        response = self.client.get(url)

        self.assertNotContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)
        self.assertNotContains(response, self.NO_ADDRESS_FILLED_IN)

    def test_job_seeker_address_not_geolocated(self):
        # Job seeker has an address filled but can't be geolocated
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerWithAddressFactory(),
        )
        self.job_seeker = self.job_application.job_seeker

        # Changed job application: new URL
        self.url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))
        response = self.client.get(self.url)

        # Check that when lookup fails, user is properly notified
        # to input employee address manually
        self.assertContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)
        self.assertNotContains(response, self.NO_ADDRESS_FILLED_IN)

        # Force the way without a profile should raise a PermissionDenied
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.pk,))
        response = self.client.get(url)

        assert response.status_code == 403

    def test_update_form_with_bad_job_seeker_address(self):
        # If HEXA address is valid, user can still change it
        # but it must be a valid one, otherwise the previous address is discarded
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Set an invalid address
        data = {
            "hexa_lane_name": "",
            "hexa_lane_type": "",
            "hexa_post_code": "xxx",
            "insee_commune_code": "xxx",
        }

        response = self.client.post(self.url, data=data)

        assert response.status_code == 200
        assert not self.job_seeker.jobseeker_profile.hexa_address_filled

    def test_address_updated_by_user(self):
        # User can now update the geolocated address if invalid

        test_data = {
            "hexa_lane_number": "15",
            "hexa_std_extension": "B",
            "hexa_lane_type": "RUE",
            "hexa_lane_name": "des colonies",
            "hexa_additional_address": "Bat A",
            "hexa_post_code": "67000",
            "hexa_commune": Commune.objects.by_insee_code("67482").pk,
        }

        data = test_data
        response = self.client.post(self.url, data=data)
        # This data set should pass
        assert response.status_code == 302

        # Check form validators

        # Lane number :
        data = test_data

        # Can't use extension without number
        data["hexa_lane_number"] = ""
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # Can't use anything else than up to 5 digits
        data["hexa_lane_number"] = "a"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_lane_number"] = "123456"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # Post code :
        data = test_data

        # 5 digits exactly
        data["hexa_post_code"] = "123456"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_post_code"] = "1234"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_lane_number"] = "1234a"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # Coherence with INSEE code
        data["hexa_lane_number"] = "12345"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # Lane name and additional address
        data = test_data

        # No special characters
        data["hexa_lane_name"] = "des colons !"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # 32 chars max
        data["hexa_lane_name"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        data = test_data
        data["hexa_additional_address"] = "Bat a !"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200

        # 32 chars max
        data["hexa_additional_address"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = self.client.post(self.url, data=data)
        assert response.status_code == 200


class CreateEmployeeRecordStep3Test(AbstractCreateEmployeeRecordTest):
    """
    Employee situation and social allowances
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerWithAddressFactory(
                born_in_france=True, with_pole_emploi_id=True, with_mocked_address=True
            ),
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
        assert form.initial["pole_emploi"]

        # Fill other mandatory field from fold
        # POST will fail because if education_level is not filled
        data = {
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi_since": "01",
            "education_level": "00",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

        self.profile.refresh_from_db()

        assert "01" == self.profile.pole_emploi_since

    def test_fold_unemployed(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["unemployed"]

        # Fill other mandatory field from fold
        data = {
            "unemployed": True,
            "unemployed_since": "02",
            "education_level": "00",
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

        self.profile.refresh_from_db()

        assert "02" == self.profile.unemployed_since

    def test_fold_rsa(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["rsa_allocation"]

        # Fill other mandatory field from fold
        data = {
            "rsa_allocation": True,
            "rsa_allocation_since": "02",
            "rsa_markup": "OUI-M",
            "education_level": "00",
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

        self.profile.refresh_from_db()

        assert "OUI-M" == self.profile.has_rsa_allocation

    def test_fold_ass(self):
        response = self.client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["ass_allocation"]

        # Fill other mandatory field from fold
        data = {
            "ass_allocation": True,
            "ass_allocation_since": "03",
            "education_level": "00",
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = self.client.post(self.url, data)

        self.assertRedirects(response, self.target_url)

        self.profile.refresh_from_db()

        assert "03" == self.profile.ass_allocation_since

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
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi": True,
        }

        # but incorrect context :
        # create another employee record with similar features
        dup_job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=self.job_seeker,
            approval=self.job_application.approval,
        )
        # Get a test commune from fixtures
        commune = CommuneFactory()

        dup_job_application.job_seeker.jobseeker_profile.education_level = "00"
        dup_job_application.job_seeker.jobseeker_profile.commune = commune
        dup_job_application.job_seeker.birth_place = commune

        dup_job_application.job_seeker.birth_country = CountryFranceFactory()
        dup_job_application.save()

        employee_record = EmployeeRecord.from_job_application(dup_job_application)
        employee_record.save()

        response = self.client.post(url, data)
        self.assertContains(
            response,
            "Il est impossible de créer cette fiche salarié pour la raison suivante",
        )


@pytest.mark.usefixtures("unittest_compatibility")
class CreateEmployeeRecordStep4Test(AbstractCreateEmployeeRecordTest):
    """
    Selection of a financial annex
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerWithAddressFactory(born_in_france=True, with_mocked_address=True),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))

        self.pass_step_3()

    def test_retrieved_employee_record_is_the_most_recent_one(self):
        older_employee_record = EmployeeRecordFactory(
            siret="00000000000000",
            job_application=self.job_application,
            created_at=self.faker.date_time(end_datetime="-1d", tzinfo=datetime.UTC),
        )
        recent_employee_record = EmployeeRecord.objects.latest("created_at")
        assert recent_employee_record != older_employee_record

        response = self.client.get(self.url)
        assert response.context["form"].employee_record == recent_employee_record


@pytest.mark.usefixtures("unittest_compatibility")
class CreateEmployeeRecordStep5Test(AbstractCreateEmployeeRecordTest):
    """
    Check summary of employee record and validation
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerWithAddressFactory(born_in_france=True, with_mocked_address=True),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_5", args=(self.job_application.id,))

        self.pass_step_4()

    def test_employee_record_status(self):
        # Employee record should now be ready to send (READY)

        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        assert employee_record.status == Status.NEW

        previous_last_checked_at = employee_record.job_application.job_seeker.last_checked_at
        # Validation of create process
        response = self.client.post(self.url)

        employee_record.refresh_from_db()
        assert employee_record.status == Status.READY
        assert employee_record.job_application.job_seeker.last_checked_at > previous_last_checked_at
        self.assertRedirects(
            response, reverse("employee_record_views:list") + "?status=NEW", fetch_redirect_response=False
        )
        [message] = list(get_messages(response.wsgi_request))
        assert message == self.snapshot

    def test_retrieved_employee_record_is_the_most_recent_one(self):
        older_employee_record = EmployeeRecordFactory(
            siret="00000000000000",
            job_application=self.job_application,
            created_at=self.faker.date_time(end_datetime="-1d", tzinfo=datetime.UTC),
        )
        recent_employee_record = EmployeeRecord.objects.latest("created_at")
        assert recent_employee_record != older_employee_record

        response = self.client.get(self.url)
        assert response.context["employee_record"] == recent_employee_record


class UpdateRejectedEmployeeRecordTest(AbstractCreateEmployeeRecordTest):
    """
    Check if update and resubmission is possible after employee record rejection
    """

    def setUp(self):
        super().setUp()
        self.job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerWithAddressFactory(born_in_france=True, with_mocked_address=True),
        )
        self.job_seeker = self.job_application.job_seeker
        self.url = reverse("employee_record_views:create_step_5", args=(self.job_application.id,))

        self.pass_step_4()

        self.client.post(self.url)

        # Reject employee record
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)

        # Must change status twice (contrained lifecycle)
        employee_record.update_as_sent("fooFileName.json", 1, None)
        assert employee_record.status == Status.SENT

        employee_record.update_as_rejected("0001", "Error message", None)

        assert employee_record.status == Status.REJECTED

        self.employee_record = employee_record

    def test_submit_after_rejection(self):
        # Validation of update process after rejection by ASP
        self.pass_step_4()

        self.client.post(self.url)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    # Simpler to test summary access from here

    def test_summary(self):
        # Check if summary is accessible
        self.pass_step_4()
        self.client.post(self.url)
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)

        self.url = reverse("employee_record_views:summary", args=(employee_record.id,))
        response = self.client.get(self.url)

        assert response.status_code == 200


# Tip: do no launch this test as standalone (unittest.skip does not work as expected)
del AbstractCreateEmployeeRecordTest
