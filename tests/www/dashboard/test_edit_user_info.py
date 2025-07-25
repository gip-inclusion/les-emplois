import math
from datetime import UTC, date, datetime

import pytest
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertFormError, assertNotContains, assertRedirects

from itou.asp.models import Commune, Country
from itou.cities.models import City
from itou.users.enums import IdentityProvider, LackOfNIRReason, LackOfPoleEmploiId, Title
from itou.users.models import JobSeekerProfile, User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.users import constants as users_test_constants
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented
from tests.www.dashboard.test_edit_job_seeker_info import DISABLED_NIR


class TestEditUserInfoView:
    NIR_UPDATE_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"
    NIR_FIELD_ID = "id_nir"
    LACK_OF_NIR_FIELD_ID = "id_lack_of_nir"
    LACK_OF_NIR_REASON_FIELD_ID = "id_lack_of_nir_reason"
    BIRTHDATE_FIELD_NAME = "birthdate"

    @pytest.fixture(autouse=True)
    def setup_method(self, mocker):
        self.city = City.objects.create(
            name="Geispolsheim",
            slug="geispolsheim-67",
            department="67",
            coords=Point(7.644817, 48.515883),
            post_codes=["67118"],
            code_insee="67152",
        )
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def address_form_fields(self, fill_mode=""):
        return {
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_line_1": "37 B Rue du Général De Gaulle",
            "address_line_2": "appartement 240",
            "insee_code": "67152",
            "post_code": "67118",
            "geocoding_score": 0.9714,
            "fill_mode": fill_mode,
        }

    def _test_address_autocomplete(self, user, post_data, ban_api_resolved_address=True):
        geocoding_data = mock_get_geocoding_data_by_ban_api_resolved(post_data["ban_api_resolved_address"])
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == self.city.name
        assert math.isclose(user.latitude, geocoding_data.get("latitude"), abs_tol=1e-5)
        assert math.isclose(user.longitude, geocoding_data.get("longitude"), abs_tol=1e-5)
        if ban_api_resolved_address:
            assert user.address_filled_at == datetime(2023, 3, 10, tzinfo=UTC)
            assert user.geocoding_updated_at == datetime(2023, 3, 10, tzinfo=UTC)

    @freeze_time("2023-03-10")
    def test_edit_with_nir(self, client, mocker, snapshot):
        user = JobSeekerFactory(jobseeker_profile__nir="178122978200508")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        with assertSnapshotQueries(snapshot):
            response = client.get(url)
        assertNotContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True)
        # There's a specific view to edit the email so we don't show it here
        assertNotContains(response, self.EMAIL_LABEL)
        # Check that the NIR field is disabled
        assertContains(response, DISABLED_NIR)
        assertContains(response, self.LACK_OF_NIR_FIELD_ID)
        assertContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        assertContains(response, self.BIRTHDATE_FIELD_NAME)
        assertContains(
            response,
            (
                '<a href="'
                f'{
                    reverse(
                        "job_seekers_views:nir_modification_request",
                        kwargs={"public_id": user.public_id},
                        query={"back_url": url},
                    )
                }">{self.NIR_UPDATE_LINK_LABEL}</a>'
            ),
            html=True,
        )

        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name == post_data["first_name"]
        assert user.last_name == post_data["last_name"]
        assert user.phone == post_data["phone"]
        assert user.jobseeker_profile.birthdate == birthdate
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot edit email here.
        assert user.email != post_data["email"]

    def test_edit_title_required(self, client):
        user = JobSeekerFactory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": user.email,
            "title": "",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": user.phone,
            "lack_of_pole_emploi_id_reason": user.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        } | self.address_form_fields()

        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]

    def test_inconsistent_nir_title_birthdate(self, client):
        birthdate = date(1978, 12, 20)
        user = JobSeekerFactory(
            jobseeker_profile__nir="178122978200508",
            title="M",
            jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        # Inconsistent title
        post_data = {
            "email": "bob@saintclar.net",
            "title": "MME",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields()
        response = client.post(url, data=post_data)

        assert response.status_code == 200
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")
        user = User.objects.get(id=user.id)

        # Ensure that the job seeker did not change the title.
        assert user.title == "M"

        # Inconsistent birthdate
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": date(1978, 11, 20).isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields()
        response = client.post(url, data=post_data)

        assert response.status_code == 200
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")
        user = User.objects.get(id=user.id)

        # Ensure that the job seeker did not change the birthdate.
        assert user.jobseeker_profile.birthdate == birthdate

    def test_validate_nir_unknown_birth_month(self, client):
        birthdate = date(1978, 12, 20)
        user = JobSeekerFactory(
            jobseeker_profile__nir="178332978200553",
            title="M",
            jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        # the month isn't between 1 and 12 -> only check for the year
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields()
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("dashboard:index"))
        user = User.objects.get(id=user.id)
        # The birthdate was updated
        assert user.jobseeker_profile.birthdate == birthdate

    def test_validate_nir_unknown_birth_month_bad_year(self, client):
        birthdate = date(1978, 12, 20)
        user = JobSeekerFactory(
            jobseeker_profile__nir="178332978200553",
            title="M",
            jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        # Inconsistant birth year
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/11/1979",
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields()
        response = client.post(url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")
        user = User.objects.get(id=user.id)

        # Ensure that the job seeker did not change the birthdate.
        assert user.jobseeker_profile.birthdate.strftime("%d/%m/%Y") != post_data["birthdate"]

    def test_required_address_fields_are_present(self, client):
        user = JobSeekerFactory(with_address=True)
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)

        # Those fields are required for the autocomplete javascript to work
        # Explicitly test the presence of the fields to help a future developer :)
        assertContains(response, 'id="id_address_line_1"')
        assertContains(response, 'id="id_address_line_2"')
        assertContains(response, 'id="id_post_code"')
        assertContains(response, 'id="id_city"')
        assertContains(response, 'id="id_insee_code"')
        assertContains(response, 'id="id_fill_mode"')
        assertContains(response, 'id="id_ban_api_resolved_address"')

    @freeze_time("2023-03-10")
    @override_settings(API_BAN_BASE_URL="http://ban-api")
    def test_update_address(self, client, snapshot):
        user = JobSeekerFactory(with_address=True, jobseeker_profile__nir="178122978200508")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        # Address is mandatory.
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }

        # Check that address field is mandatory
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("address_for_autocomplete") == ["Ce champ est obligatoire."]

        # Check that when we post a different address than the one of the user and
        # there is an error in the form (title is missing), the new address is displayed in the select
        # instead of the one attached to the user
        response = client.post(url, data=post_data | {"title": ""} | self.address_form_fields(fill_mode="ban_api"))
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert pretty_indented(results_section) == snapshot(name="user address input on error")

        # Now try again in fallback mode (ban_api_resolved_address is missing)
        post_data = post_data | self.address_form_fields(fill_mode="fallback")
        response = client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=False)

        # Now try again providing every required field.
        post_data = post_data | self.address_form_fields(fill_mode="ban_api")
        response = client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=True)

        # Ensure the job seeker's address is displayed in the autocomplete input field.
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert pretty_indented(results_section) == snapshot(name="user address input")

    def test_update_address_unavailable_api(self, client):
        user = JobSeekerFactory(jobseeker_profile__nir="178122978200508")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        # Address is mandatory.
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            # Address fallback fields,
            "address_for_autocomplete": "26 rue du Labrador",
            "address_line_1": "102 Quai de Jemmapes",
            "address_line_2": "Appartement 16",
            "post_code": "75010",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]

    @freeze_time("2023-03-10")
    def test_edit_with_lack_of_nir_reason(self, client):
        user = JobSeekerFactory(
            jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER
        )
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        # Check that the NIR field is disabled (it can be reenabled via lack_of_nir check box)
        assertContains(response, DISABLED_NIR)
        assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        assertNotContains(response, self.NIR_UPDATE_LINK_LABEL, html=True)
        assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        NEW_NIR = "1 781 22978200508"
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields(fill_mode="ban_api")

        response = client.post(url, data=post_data)
        assert response.status_code == 302

        user.refresh_from_db()
        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")
        self._test_address_autocomplete(user=user, post_data=post_data)

    @freeze_time("2023-03-10")
    def test_edit_without_nir_information(self, client):
        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        assertNotContains(response, self.NIR_UPDATE_LINK_LABEL, html=True)

        NEW_NIR = "1 781 22978200508"
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields()
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

    def test_edit_existing_nir(self, client):
        other_jobseeker = JobSeekerFactory()

        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        assertNotContains(response, self.NIR_UPDATE_LINK_LABEL, html=True)

        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": other_jobseeker.jobseeker_profile.nir,
        }
        response = client.post(url, data=post_data)
        assertContains(response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur")

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == ""

    def test_only_birth_country(self, client):
        user = JobSeekerFactory(jobseeker_profile__nir="178122978200508", born_outside_france=True)
        birth_country = user.jobseeker_profile.birth_country
        client.force_login(user)
        birthdate = date(1978, 12, 20)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_country": birth_country.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = client.post(reverse("dashboard:edit_user_info"), data=post_data)
        assertRedirects(response, reverse("dashboard:index"))
        user = User.objects.select_related("jobseeker_profile").get(pk=user.id)
        assert user.jobseeker_profile.birth_country_id == birth_country.pk

    def test_born_in_france_no_birthplace(self, client):
        user = JobSeekerFactory(jobseeker_profile__nir="178122978200508")
        client.force_login(user)
        birthdate = date(1978, 12, 20)
        birth_country = Country.objects.get(code=Country.INSEE_CODE_FRANCE)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_country": birth_country.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = client.post(reverse("dashboard:edit_user_info"), data=post_data)
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
        user = User.objects.select_related("jobseeker_profile").get(pk=user.id)
        assert user.jobseeker_profile.birth_country_id is None

    def test_accept_born_outside_of_france_specifies_birth_place(self, client):
        user = JobSeekerFactory(jobseeker_profile__nir="178122978200508")
        client.force_login(user)
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        birth_country = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first()
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_country": birth_country.pk,
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = client.post(reverse("dashboard:edit_user_info"), data=post_data)
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
        assert user.jobseeker_profile.birth_country_id is None

    def test_fields_readonly_with_certified_criteria(self, client):
        job_seeker = JobSeekerFactory(
            title=Title.M,
            born_in_france=True,
            jobseeker_profile__birthdate=date(1978, 12, 20),
            jobseeker_profile__nir="178122978200508",
        )
        IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__job_seeker=job_seeker,
            certified=True,
        )
        client.force_login(job_seeker)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        assertContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True, count=1)
        birthdate = date(1978, 12, 1)
        response = client.post(
            url,
            {
                "email": "bob@saintclar.net",
                "title": "M",
                "first_name": "Bob",
                "last_name": "Saint Clar",
                "birthdate": birthdate.isoformat(),
                "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
                "phone": "0610203050",
                "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
                "address_line_1": "10 rue du Gué",
                "address_line_2": "Sous l'escalier",
                "post_code": "35400",
                "city": "Saint-Malo",
                "lack_of_nir": False,
                "nir": job_seeker.jobseeker_profile.nir,
            },
        )
        assertRedirects(response, reverse("dashboard:index"))
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        for attr in ["title", "first_name", "last_name"]:
            assert getattr(refreshed_job_seeker, attr) == getattr(job_seeker, attr)
        for attr in ["birthdate", "birth_place", "birth_country"]:
            assert getattr(refreshed_job_seeker.jobseeker_profile, attr) == getattr(job_seeker.jobseeker_profile, attr)

    @freeze_time("2023-03-10")
    def test_edit_sso(self, client):
        user = JobSeekerFactory(
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            first_name="Not Bob",
            last_name="Not Saint Clar",
            jobseeker_profile__birthdate=date(1970, 1, 1),
            title="M",
        )
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        assertContains(response, self.EMAIL_LABEL)

        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")

        response = client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot update data retrieved from the SSO here.
        assert user.first_name != post_data["first_name"]
        assert user.last_name != post_data["last_name"]
        assert user.jobseeker_profile.birthdate != birthdate
        assert user.email != post_data["email"]

    def test_edit_without_title(self, client, snapshot):
        MISSING_INFOS_WARNING_ID = "missing-infos-warning"
        user = JobSeekerFactory(with_address=True, title="", phone="", address_line_1="")
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        # No phone and no title and no address
        response = client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert pretty_indented(warning_text) == snapshot(name="missing title warning with phone and address")

        # Phone but no title and no birthdate
        user.phone = "0123456789"
        user.address_line_1 = "123 rue de"
        user.save(
            update_fields=(
                "address_line_1",
                "phone",
            )
        )
        user.jobseeker_profile.birthdate = None
        user.jobseeker_profile.save(update_fields={"birthdate"})
        response = client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert pretty_indented(warning_text) == snapshot(name="missing title warning without phone and with birthdate")

        # No phone but title
        user.phone = ""
        user.title = Title.MME
        user.save(update_fields=("phone", "title"))
        response = client.get(url)
        assertNotContains(response, MISSING_INFOS_WARNING_ID)

    def test_edit_with_invalid_pole_emploi_id(self, client):
        user = JobSeekerFactory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        birthdate = date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": user.email,
            "title": user.title,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "phone": user.phone,
            "pole_emploi_id": "1234567890A",  # 11 chars with a letter : wrong format
            "lack_of_pole_emploi_id_reason": "",
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assertFormError(
            response.context["form"], "pole_emploi_id", "Le format de l’identifiant France Travail est invalide."
        )

    def test_edit_as_prescriber_PC(self, client):
        original_user = PrescriberFactory(
            email="bob@saintclair.tld",
            first_name="Not Bob",
            last_name="Not Saint Clair",
            phone="0600000000",
        )
        client.force_login(original_user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        assertNotContains(response, self.NIR_FIELD_ID)
        assertNotContains(response, self.LACK_OF_NIR_FIELD_ID)
        assertNotContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        assertNotContains(response, self.BIRTHDATE_FIELD_NAME)
        assertContains(response, f"Prénom : <strong>{original_user.first_name.title()}</strong>")
        assertContains(response, f"Nom : <strong>{original_user.last_name.upper()}</strong>")
        assertContains(response, f"Adresse e-mail : <strong>{original_user.email}</strong>")
        assertContains(response, "Ces informations doivent être modifiées sur votre compte ")

        post_data = {
            "email": "notbob@notsaintclair.com",
            "first_name": "Bob",
            "last_name": "Saint Clair",
            "phone": "0610203050",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        updated_user = User.objects.get(pk=original_user.pk)
        assert updated_user.email == original_user.email
        assert updated_user.first_name == original_user.first_name
        assert updated_user.last_name == original_user.last_name
        assert updated_user.phone == post_data["phone"]
