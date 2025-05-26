import datetime
import random

import freezegun
import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.asp.models import Commune, Country, EducationLevel
from itou.companies.enums import CompanyKind
from itou.companies.models import SiaeFinancialAnnex
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordTransition
from itou.users.enums import LackOfNIRReason, Title
from itou.users.models import User
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_FOR_SNAPSHOT_MOCK, mock_get_geocoding_data
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from tests.companies.factories import CompanyWithMembershipAndJobsFactory, SiaeFinancialAnnexFactory
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory
from tests.users import constants as users_test_constants
from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


# Helper functions
def _get_user_form_data(user):
    form_data = {
        "title": "M",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "birthdate": user.jobseeker_profile.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
    }
    if user.jobseeker_profile.birth_country:
        form_data["birth_country"] = user.jobseeker_profile.birth_country_id
    if user.jobseeker_profile.birth_place:
        form_data["birth_place"] = user.jobseeker_profile.birth_place_id
    return form_data


class CreateEmployeeRecordTestMixin:
    URL_NAME = None
    SIAE_KIND = random.choice(CompanyKind.siae_kinds())

    @pytest.fixture(autouse=True)
    def abstract_setup_method(self, mocker):
        self.company = CompanyWithMembershipAndJobsFactory(
            name="Evil Corp.", membership__user__first_name="Elliot", kind=self.SIAE_KIND
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
            job_seeker__with_mocked_address=True,
            job_seeker__born_in_france=True,
            job_seeker__with_pole_emploi_id=True,
            job_seeker__jobseeker_profile__with_required_eiti_fields=True,
        )

        self.job_seeker = self.job_application.job_seeker

        self.url = reverse(self.URL_NAME, args=(self.job_application.pk,))

        mocker.patch(
            "itou.common_apps.address.format.get_geocoding_data",
            side_effect=mock_get_geocoding_data,
        )

    # Bypass each step with minimum viable data

    def pass_step_1(self, client):
        client.force_login(self.user)
        url = reverse("employee_record_views:create", args=(self.job_application.id,))
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        data = _get_user_form_data(self.job_seeker)
        response = client.post(url, data=data)

        assertRedirects(response, target_url)

        return response

    def pass_step_2(self, client):
        self.pass_step_1(client)
        url = reverse("employee_record_views:create_step_2", args=(self.job_application.id,))
        client.get(url)

        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.hexa_address_filled

        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        response = client.get(url)

        assert response.status_code == 200

    def _default_step_3_data(self):
        data = {
            "education_level": "00",
            # Factory user is register to Pôle emploi: all fields must be filled
            "pole_emploi_since": "02",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi": True,
        }
        if self.company.kind == CompanyKind.EITI:
            data.update(
                actor_met_for_business_creation=self.job_application.job_seeker.jobseeker_profile.actor_met_for_business_creation,
                mean_monthly_income_before_process=self.job_application.job_seeker.jobseeker_profile.mean_monthly_income_before_process,
                eiti_contributions=self.job_application.job_seeker.jobseeker_profile.eiti_contributions,
            )
        return data

    def pass_step_3(self, client):
        self.pass_step_2(client)
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        client.get(url)

        response = client.post(url, self._default_step_3_data())

        assert response.status_code == 302

    def pass_step_4(self, client):
        self.pass_step_3(client)
        url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))
        client.get(url)

        # Do not use financial annex number om ModelChoiceField: must pass an ID !
        data = {"financial_annex": self.company.convention.financial_annexes.first().id}
        response = client.post(url, data)

        assert response.status_code == 302

    # Perform check permissions for each step

    def test_access_granted(self, client):
        # Must have access
        client.force_login(self.user)
        response = client.get(self.url)

        assert response.status_code == 200

    def test_access_denied_bad_permissions(self, client):
        # Must not have access
        client.force_login(self.user_without_perms)

        response = client.get(self.url)
        # Changed to 404
        assert response.status_code == 404

    def test_access_denied_bad_siae_kind(self, client):
        # SIAE can't use employee record (not the correct kind)
        client.force_login(self.user_siae_bad_kind)

        response = client.get(self.url)

        assert response.status_code == 403

    def test_access_denied_nir_associated_to_other(self, client):
        self.job_seeker = self.job_application.job_seeker
        self.job_seeker.jobseeker_profile.nir = ""
        self.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        self.job_seeker.jobseeker_profile.save(update_fields=("nir", "lack_of_nir_reason"))

        client.force_login(self.user)
        response = client.get(self.url)

        assertContains(response, "régulariser le numéro de sécurité sociale", status_code=403)


class TestCreateEmployeeRecordStep1(CreateEmployeeRecordTestMixin):
    """
    Employee details form: title and birth place
    """

    URL_NAME = "employee_record_views:create"

    def test_title(self, client):
        # Job seeker / employee must have a title

        client.force_login(self.user)
        response = client.get(self.url)
        assertNotContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True)

        data = _get_user_form_data(self.job_seeker)
        data.pop("title")

        response = client.post(self.url, data=data)
        assert 200 == response.status_code

        data["title"] = "MME"
        response = client.post(self.url, data=data)

        assertRedirects(response, reverse("employee_record_views:create_step_2", args=(self.job_application.pk,)))

    def test_bad_birthplace(self, client):
        # If birth country is France, a commune (INSEE) is mandatory
        # otherwise, only a country is mandatory

        # Validation is done by the model
        client.force_login(self.user)
        client.get(self.url)

        data = _get_user_form_data(self.job_seeker)

        # France as birth country without commune
        data["birth_country"] = Country.objects.get(name="FRANCE").pk
        data.pop("birth_place")
        response = client.post(self.url, data=data)

        assert 200 == response.status_code

    def test_birthplace_in_france(self, client):
        client.force_login(self.user)
        client.get(self.url)
        data = _get_user_form_data(self.job_seeker)
        birth_place = Commune.objects.by_insee_code_and_period("07141", self.job_seeker.jobseeker_profile.birthdate)
        data["birth_place"] = birth_place.pk
        # Birth country field is automatically set with Javascript and disabled.
        # Disabled fields are not sent with POST data.
        del data["birth_country"]
        response = client.post(self.url, data=data)

        # Redirects must go to step 2
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

        # Default test values are ok
        assertRedirects(response, target_url)

    def test_birthplace_outside_of_france(self, client):
        client.force_login(self.user)
        client.get(self.url)

        data = _get_user_form_data(self.job_seeker)
        data.pop("birth_place")
        data["birth_country"] = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first().pk

        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))
        response = client.post(self.url, data=data)

        assertRedirects(response, target_url)

    def test_born_in_france_no_birthplace(self, client):
        client.force_login(self.user)
        client.get(self.url)
        data = _get_user_form_data(self.job_seeker)
        del data["birth_place"]
        response = client.post(self.url, data=data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>Si le pays de naissance est la France, la commune de naissance est obligatoire.</li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    def test_born_outside_of_france_specifies_birthplace(self, client):
        client.force_login(self.user)
        client.get(self.url)
        data = _get_user_form_data(self.job_seeker)
        data["birth_country"] = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first().pk
        response = client.post(self.url, data=data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>Il n'est pas possible de saisir une commune de naissance hors de France.</li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    def test_accept_personal_data_readonly_with_certified_criteria(self, client):
        IAESelectedAdministrativeCriteriaFactory(eligibility_diagnosis__job_seeker=self.job_seeker, certified=True)
        client.force_login(self.user)
        response = client.get(self.url)
        assertContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True, count=1)
        response = client.post(
            self.url,
            data={
                "title": Title.M if self.job_seeker.title == Title.MME else Title.MME,
                "first_name": "Léon",
                "last_name": "Munitionette",
                "birth_place": Commune.objects.by_insee_code_and_period("07141", datetime.date(1990, 1, 1)).pk,
                "birthdate": "1990-01-01",
            },
        )
        assertRedirects(response, reverse("employee_record_views:create_step_2", args=(self.job_application.pk,)))
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=self.job_seeker.pk)
        for attr in ["title", "first_name", "last_name"]:
            assert getattr(refreshed_job_seeker, attr) == getattr(self.job_seeker, attr)
        for attr in ["birthdate", "birth_place", "birth_country"]:
            assert getattr(refreshed_job_seeker.jobseeker_profile, attr) == getattr(
                self.job_seeker.jobseeker_profile, attr
            )

    def test_pass_step_1_without_geolocated_address(self, client):
        # Do not mess with job seeker profile and geolocation at step 1
        # just check user model info

        client.force_login(self.user)
        client.get(self.url)

        # No geoloc mock used, basic factory with:
        # - simple / fake address
        # - birth place and country
        data = _get_user_form_data(JobSeekerFactory.build(with_address=True, born_in_france=True))
        response = client.post(self.url, data=data)

        # Redirects must go to step 2
        target_url = reverse("employee_record_views:create_step_2", args=(self.job_application.pk,))

        assertRedirects(response, target_url)


class TestCreateEmployeeRecordStep2(CreateEmployeeRecordTestMixin):
    NO_ADDRESS_FILLED_IN = "Aucune adresse n'a été saisie sur les emplois de l'inclusion !"
    ADDRESS_COULD_NOT_BE_AUTO_CHECKED = "L'adresse du salarié n'a pu être vérifiée automatiquement."

    URL_NAME = "employee_record_views:create_step_2"

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.pass_step_1(client)

    def test_job_seeker_without_address(self, client):
        # Job seeker has no address filled (which should not happen without admin operation)
        job_application = JobApplicationWithApprovalNotCancellableFactory(to_company=self.company)

        response = client.get(self.url)
        url = reverse("employee_record_views:create_step_2", args=(job_application.pk,))
        response = client.get(url)

        assertContains(response, self.NO_ADDRESS_FILLED_IN)
        assertContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)

    def test_job_seeker_address_geolocated(self, client, snapshot):
        job_seeker = JobSeekerFactory(
            for_snapshot=True,
            with_mocked_address=BAN_GEOCODING_API_RESULTS_FOR_SNAPSHOT_MOCK,
        )
        job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=job_seeker,
        )

        # Accept geolocated address provided by mock and pass to step 3
        response = client.get(reverse("employee_record_views:create_step_2", args=(job_application.pk,)))
        form_soup = parse_response_to_soup(
            response,
            selector=".s-section form",
            replace_in_attr=[
                (
                    "action",
                    reverse("employee_record_views:create_step_2", args=(job_application.pk,)),
                    "/employee_record/create_step_2/[PK of JobApplication]",
                ),
                (
                    "href",
                    reverse("employee_record_views:create_step_3", args=(job_application.pk,)),
                    "/employee_record/create_step_3/[PK of JobApplication]",
                ),  # Go to next step button
                (
                    "href",
                    reverse("employee_record_views:create", args=(job_application.pk,)),
                    "/employee_record/create/[PK of JobApplication]",
                ),  # Go to previous step button
            ],
        )
        assert pretty_indented(form_soup) == snapshot

        response = client.get(reverse("employee_record_views:create_step_3", args=(job_application.pk,)))
        assertNotContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)
        assertNotContains(response, self.NO_ADDRESS_FILLED_IN)

    def test_job_seeker_address_not_geolocated(self, client):
        # Job seeker has an address filled but can't be geolocated
        job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=JobSeekerFactory(with_address=True),
        )

        # Changed job application: new URL
        response = client.get(reverse(self.URL_NAME, args=(job_application.pk,)))

        # Check that when lookup fails, user is properly notified
        # to input employee address manually
        assertContains(response, self.ADDRESS_COULD_NOT_BE_AUTO_CHECKED)
        assertNotContains(response, self.NO_ADDRESS_FILLED_IN)

        # Force the way without a profile should raise a PermissionDenied
        response = client.get(reverse("employee_record_views:create_step_3", args=(job_application.pk,)))

        assert response.status_code == 403

    def test_update_form_with_bad_job_seeker_address(self, client):
        # If HEXA address is valid, user can still change it
        # but it must be a valid one, otherwise the previous address is discarded
        response = client.get(self.url)
        assert response.status_code == 200

        # Set an invalid address
        data = {
            "hexa_lane_name": "",
            "hexa_lane_type": "",
            "hexa_post_code": "xxx",
            "insee_commune_code": "xxx",
        }

        response = client.post(self.url, data=data)

        assert response.status_code == 200
        assert not self.job_seeker.jobseeker_profile.hexa_address_filled

    def test_address_updated_by_user(self, client):
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
        response = client.post(self.url, data=data)
        # This data set should pass
        assert response.status_code == 302

        # Check form validators

        # Lane number :
        data = test_data

        # Can't use extension without number
        data["hexa_lane_number"] = ""
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # Can't use anything else than up to 5 digits
        data["hexa_lane_number"] = "a"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_lane_number"] = "123456"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # Post code :
        data = test_data

        # 5 digits exactly
        data["hexa_post_code"] = "123456"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_post_code"] = "1234"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        data["hexa_lane_number"] = "1234a"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # Coherence with INSEE code
        data["hexa_lane_number"] = "12345"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # Lane name and additional address
        data = test_data

        # No special characters
        data["hexa_lane_name"] = "des colons !"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # 32 chars max
        data["hexa_lane_name"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        data = test_data
        data["hexa_additional_address"] = "Bat a !"
        response = client.post(self.url, data=data)
        assert response.status_code == 200

        # 32 chars max
        data["hexa_additional_address"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        response = client.post(self.url, data=data)
        assert response.status_code == 200


class TestCreateEmployeeRecordStep3(CreateEmployeeRecordTestMixin):
    """
    Employee situation and social allowances
    """

    URL_NAME = "employee_record_views:create_step_3"
    SIAE_KIND = random.choice(list(set(CompanyKind.siae_kinds()) - {CompanyKind.EITI}))

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.target_url = reverse("employee_record_views:create_step_4", args=(self.job_application.id,))

        self.pass_step_2(client)

    # Most of coherence test are done in the model

    # "Basic" folds : check invalidation of hidden fields

    def test_fold_pole_emploi(self, client, mocker):
        mocker.patch(
            "itou.common_apps.address.format.get_geocoding_data",
            side_effect=mock_get_geocoding_data,
        )
        # Test behaviour of Pôle Emploi related fields
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must be pre-checked if job seeker has a Pôle emploi ID
        assert form.initial["pole_emploi"]

        # Fill other mandatory field from fold
        # POST will fail because if education_level is not filled
        data = {
            **self._default_step_3_data(),
            "pole_emploi": True,
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "pole_emploi_since": "01",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "01" == self.job_seeker.jobseeker_profile.pole_emploi_since

    def test_fold_unemployed(self, client):
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["unemployed"]

        # Fill other mandatory field from fold
        data = {
            **self._default_step_3_data(),
            "unemployed": True,
            "unemployed_since": "02",
            "education_level": "00",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "02" == self.job_seeker.jobseeker_profile.unemployed_since

    def test_fold_rsa(self, client):
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["rsa_allocation"]

        # Fill other mandatory field from fold
        data = {
            **self._default_step_3_data(),
            "rsa_allocation": True,
            "rsa_allocation_since": "02",
            "rsa_markup": "OUI-M",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "OUI-M" == self.job_seeker.jobseeker_profile.has_rsa_allocation

    def test_fold_ass(self, client):
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["ass_allocation"]

        # Fill other mandatory field from fold
        data = {
            **self._default_step_3_data(),
            "ass_allocation": True,
            "ass_allocation_since": "03",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "03" == self.job_seeker.jobseeker_profile.ass_allocation_since

    def test_fail_step_3(self, client):
        self.job_seeker.jobseeker_profile.education_level = EducationLevel.NON_CERTIFYING_QUALICATIONS
        self.job_seeker.jobseeker_profile.save(update_fields=["education_level"])
        # If anything goes wrong during employee record creation,
        # catch error / exceptions and display a message
        self.pass_step_2(client)
        url = reverse("employee_record_views:create_step_3", args=(self.job_application.id,))
        client.get(url)

        # Incorrect context:
        # create another employee record with similar features
        dup_job_application = JobApplicationWithApprovalNotCancellableFactory(
            to_company=self.company,
            job_seeker=self.job_seeker,
            approval=self.job_application.approval,
        )

        employee_record = EmployeeRecord.from_job_application(dup_job_application)
        employee_record.save()

        # But correct data:
        response = client.post(url, self._default_step_3_data())
        assertContains(
            response,
            "Il est impossible de créer cette fiche salarié pour la raison suivante",
        )


class TestCreateEmployeeRecordStep3ForEITI(TestCreateEmployeeRecordStep3):
    """
    Employee situation and social allowances
    """

    SIAE_KIND = CompanyKind.EITI

    def test_fold_are_allocation(self, client):
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["are_allocation"]

        # Fill other mandatory field from fold
        data = {
            **self._default_step_3_data(),
            "are_allocation": True,
            "are_allocation_since": "03",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "03" == self.job_seeker.jobseeker_profile.are_allocation_since

    def test_fold_activity_bonus(self, client):
        response = client.get(self.url)
        form = response.context["form"]

        # Checkbox must not pre-checked: this value is unknown at this stage
        assert not form.initial["activity_bonus"]

        # Fill other mandatory field from fold
        data = {
            **self._default_step_3_data(),
            "activity_bonus": True,
            "activity_bonus_since": "03",
        }
        response = client.post(self.url, data)

        assertRedirects(response, self.target_url)

        self.job_seeker.jobseeker_profile.refresh_from_db()

        assert "03" == self.job_seeker.jobseeker_profile.activity_bonus_since


class TestCreateEmployeeRecordStep4(CreateEmployeeRecordTestMixin):
    """
    Selection of a financial annex
    """

    URL_NAME = "employee_record_views:create_step_4"

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.pass_step_3(client)

    def test_retrieved_employee_record_is_the_most_recent_one(self, client, faker):
        older_employee_record = EmployeeRecordFactory(
            siret="00000000000000",
            job_application=self.job_application,
            created_at=faker.date_time(end_datetime="-1d", tzinfo=datetime.UTC),
        )
        recent_employee_record = EmployeeRecord.objects.latest("created_at")
        assert recent_employee_record != older_employee_record

        response = client.get(self.url)
        assert response.context["form"].employee_record == recent_employee_record

    def test_financial_annexes_ordering(self, client):
        current_annex = self.company.convention.financial_annexes.get()
        old_annex = SiaeFinancialAnnexFactory(
            convention=self.company.convention,
            state=SiaeFinancialAnnex.STATE_ARCHIVED,
            start_at=timezone.localdate() - datetime.timedelta(days=730),
            end_at=timezone.localdate() - datetime.timedelta(days=365),
        )
        response = client.get(self.url)
        assertContains(
            response,
            f"""
            <select name="financial_annex" lang="fr" data-minimum-input-length="0"
                    data-theme="bootstrap-5" data-allow-clear="true" data-placeholder=""
                    class="form-select django-select2" id="id_financial_annex">
              <option value="" selected></option>
              <option value="{current_annex.pk}">
                  {current_annex.number}
                  — {current_annex.start_at:%d/%m/%Y}–{current_annex.end_at:%d/%m/%Y}
                  — Validée
                  </option>
              <option value="{old_annex.pk}">
                  {old_annex.number}
                  — {old_annex.start_at:%d/%m/%Y}–{old_annex.end_at:%d/%m/%Y}
                  — Archivée (invalide)
              </option>
            </select>
            """,
            html=True,
            count=1,
        )


class TestCreateEmployeeRecordStep5(CreateEmployeeRecordTestMixin):
    """
    Check summary of employee record and validation
    """

    URL_NAME = "employee_record_views:create_step_5"
    SIAE_KIND = random.choice(list(set(CompanyKind.siae_kinds()) - {CompanyKind.EITI}))

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.pass_step_4(client)

    def test_employee_record_status(self, client, snapshot):
        # Employee record should now be ready to send (READY)

        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        assert employee_record.status == Status.NEW

        previous_last_checked_at = employee_record.job_application.job_seeker.last_checked_at
        # Validation of create process
        response = client.post(self.url)

        employee_record.refresh_from_db()
        assert employee_record.status == Status.READY
        assert employee_record.job_application.job_seeker.last_checked_at > previous_last_checked_at
        assertRedirects(response, reverse("employee_record_views:list") + "?status=NEW", fetch_redirect_response=False)
        [message] = list(get_messages(response.wsgi_request))
        assert message == snapshot

    @freezegun.freeze_time("2025-02-25")
    def test_hiring_starts_in_future(self, client, snapshot):
        self.job_application.hiring_start_at = timezone.localdate() + datetime.timedelta(days=1)
        self.job_application.save(update_fields={"hiring_start_at", "updated_at"})
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        assert employee_record.status == Status.NEW

        response = client.get(self.url)
        assert str(
            parse_response_to_soup(
                response,
                selector=".s-section .alert.alert-warning",
                replace_in_attr=[],
            )
        ) == snapshot(name="alert")
        assert str(
            parse_response_to_soup(
                response,
                selector=".s-section form",
                replace_in_attr=[
                    (
                        "action",
                        f"/employee_record/create_step_5/{self.job_application.pk}",
                        "/employee_record/create_step_5/[JOB APPLICATION PK]",
                    ),
                    (
                        "href",
                        f"/employee_record/create_step_4/{self.job_application.pk}",
                        "/employee_record/create_step_4/[JOB APPLICATION PK]",
                    ),
                ],
            )
        ) == snapshot(name="form")

    def test_retrieved_employee_record_is_the_most_recent_one(self, client, faker):
        older_employee_record = EmployeeRecordFactory(
            siret="00000000000000",
            job_application=self.job_application,
            created_at=faker.date_time(end_datetime="-1d", tzinfo=datetime.UTC),
        )
        recent_employee_record = EmployeeRecord.objects.latest("created_at")
        assert recent_employee_record != older_employee_record

        response = client.get(self.url)
        assert response.context["employee_record"] == recent_employee_record

    def test_eiti_fields_display(self, client):
        response = client.get(self.url)
        assertNotContains(response, "Bénéficiaire de l'ARE depuis")
        assertNotContains(response, "Bénéficiaire de la prime d'activité depuis")
        assertNotContains(response, "Bénéficiaire CAPE")
        assertNotContains(response, "Bénéficiaire CESA")
        assertNotContains(response, "Acteur rencontré : ")
        assertNotContains(response, "Revenu brut mensuel moyen : ")
        assertNotContains(response, "Taux de cotisation : ")

    def test_transition_log(self, client):
        employee_record = EmployeeRecord.objects.get(job_application=self.job_application)

        assert employee_record.logs.count() == 0
        client.post(self.url)

        log = employee_record.logs.get()
        assert log.transition == EmployeeRecordTransition.READY
        assert log.user == self.user


class TestCreateEmployeeRecordStep5ForEITI(TestCreateEmployeeRecordStep5):
    SIAE_KIND = CompanyKind.EITI

    def _default_step_3_data(self):
        return {
            **super()._default_step_3_data(),
            "are_allocation": True,
            "are_allocation_since": "03",
            "activity_bonus": True,
            "activity_bonus_since": "03",
            "cape_freelance": True,
            "cesa_freelance": True,
        }

    def test_eiti_fields_display(self, client):
        response = client.get(self.url)
        assertContains(response, "Bénéficiaire de l'ARE depuis")
        assertContains(response, "Bénéficiaire de la prime d'activité depuis")
        assertContains(response, "Bénéficiaire CAPE")
        assertContains(response, "Bénéficiaire CESA")
        assertContains(response, "Acteur rencontré : ")
        assertContains(response, "Revenu brut mensuel moyen : ")
        assertContains(response, "Taux de cotisation : ")


class TestUpdateRejectedEmployeeRecord(CreateEmployeeRecordTestMixin):
    """
    Check if update and resubmission is possible after employee record rejection
    """

    URL_NAME = "employee_record_views:create_step_5"

    def _default_step_3_data(self):
        data = super()._default_step_3_data()
        if self.company.kind == CompanyKind.EITI:
            data.update(
                actor_met_for_business_creation=self.job_application.job_seeker.jobseeker_profile.actor_met_for_business_creation,
                mean_monthly_income_before_process=self.job_application.job_seeker.jobseeker_profile.mean_monthly_income_before_process,
                eiti_contributions=self.job_application.job_seeker.jobseeker_profile.eiti_contributions,
            )
        return data

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.pass_step_4(client)

        # Reject employee record
        self.employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        self.employee_record.status = Status.REJECTED
        self.employee_record.save(update_fields={"status", "updated_at"})

    def test_submit_after_rejection(self, client):
        client.post(self.url)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY


class TestResendProcessedEmployeeRecord(CreateEmployeeRecordTestMixin):
    URL_NAME = "employee_record_views:create_step_5"

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.pass_step_4(client)

        # Set employee record as PROCESSED
        self.employee_record = EmployeeRecord.objects.get(job_application=self.job_application)
        self.employee_record.status = Status.PROCESSED
        self.employee_record.save(update_fields={"status", "updated_at"})

    def test_resubmit_processed_record(self, client, snapshot):
        response = client.post(self.url)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY
        assertRedirects(response, add_url_params(reverse("employee_record_views:list"), {"status": "PROCESSED"}))
        [message] = list(get_messages(response.wsgi_request))
        assert message == snapshot
