import math
from datetime import UTC, date, datetime
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time

from itou.cities.models import City
from itou.users.enums import IdentityProvider, LackOfNIRReason, LackOfPoleEmploiId, Title
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from tests.openid_connect.inclusion_connect.test import (
    InclusionConnectBaseTestCase,
)
from tests.users.factories import (
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import BASE_NUM_QUERIES, parse_response_to_soup
from tests.www.dashboard.test_edit_job_seeker_info import DISABLED_NIR


@pytest.mark.usefixtures("unittest_compatibility")
class EditUserInfoViewTest(InclusionConnectBaseTestCase):
    NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"
    NIR_FIELD_ID = "id_nir"
    LACK_OF_NIR_FIELD_ID = "id_lack_of_nir"
    LACK_OF_NIR_REASON_FIELD_ID = "id_lack_of_nir_reason"
    BIRTHDATE_FIELD_NAME = "birthdate"

    def setUp(self):
        super().setUp()
        self.city = City.objects.create(
            name="Geispolsheim",
            slug="geispolsheim-67",
            department="67",
            coords=Point(7.644817, 48.515883),
            post_codes=["67118"],
            code_insee="67152",
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

    @override_settings(TALLY_URL="https://tally.so")
    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_with_nir(self, _mock):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # session
            + 1  # user
            + 1  # jobseeker_profile
            + 1  # external_data_externaldataimport (extra_data)
            + 3  # update session with savepoint & release
        ):
            response = self.client.get(url)
        # There's a specific view to edit the email so we don't show it here
        self.assertNotContains(response, self.EMAIL_LABEL)
        # Check that the NIR field is disabled
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(response, self.LACK_OF_NIR_FIELD_ID)
        self.assertContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        self.assertContains(response, self.BIRTHDATE_FIELD_NAME)
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobseeker={user.pk}" target="_blank" rel="noopener">'
                f"{self.NIR_UPDATE_TALLY_LINK_LABEL}</a>"
            ),
            html=True,
        )

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name == post_data["first_name"]
        assert user.last_name == post_data["last_name"]
        assert user.phone == post_data["phone"]
        assert user.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot edit email here.
        assert user.email != post_data["email"]

    def test_edit_title_required(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        post_data = {
            "email": user.email,
            "title": "",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": "20/12/1978",
            "phone": user.phone,
            "lack_of_pole_emploi_id_reason": user.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        } | self.address_form_fields()

        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]

    def test_required_address_fields_are_present(self):
        user = JobSeekerFactory(with_address=True)
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)

        # Those fields are required for the autocomplete javascript to work
        # Explicitly test the presence of the fields to help a future developer :)
        self.assertContains(response, 'id="id_address_line_1"')
        self.assertContains(response, 'id="id_address_line_2"')
        self.assertContains(response, 'id="id_post_code"')
        self.assertContains(response, 'id="id_city"')
        self.assertContains(response, 'id="id_insee_code"')
        self.assertContains(response, 'id="id_fill_mode"')
        self.assertContains(response, 'id="id_ban_api_resolved_address"')

    @pytest.mark.usefixtures("unittest_compatibility")
    @freeze_time("2023-03-10")
    @override_settings(API_BAN_BASE_URL="http://ban-api")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_update_address(self, _mock):
        user = JobSeekerFactory(with_address=True)
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Address is mandatory.
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }

        # Check that address field is mandatory
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("address_for_autocomplete") == ["Ce champ est obligatoire."]

        # Check that when we post a different address than the one of the user and
        # there is an error in the form (title is missing), the new address is displayed in the select
        # instead of the one attached to the user
        response = self.client.post(
            url, data=post_data | {"title": ""} | self.address_form_fields(fill_mode="ban_api")
        )
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert str(results_section) == self.snapshot(name="user address input on error")

        # Now try again in fallback mode (ban_api_resolved_address is missing)
        post_data = post_data | self.address_form_fields(fill_mode="fallback")
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=False)

        # Now try again providing every required field.
        post_data = post_data | self.address_form_fields(fill_mode="ban_api")
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=True)

        # Ensure the job seeker's address is displayed in the autocomplete input field.
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert str(results_section) == self.snapshot(name="user address input")

    def test_update_address_unavailable_api(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Address is mandatory.
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            # Address fallback fields,
            "address_for_autocomplete": "26 rue du Labrador",
            "address_line_1": "102 Quai de Jemmapes",
            "address_line_2": "Appartement 16",
            "post_code": "75010",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]

    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_with_lack_of_nir_reason(self, _mock):
        user = JobSeekerFactory(
            jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER
        )
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is disabled (it can be reenabled via lack_of_nir check box)
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)
        self.assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields(fill_mode="ban_api")

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.refresh_from_db()
        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")
        self._test_address_autocomplete(user=user, post_data=post_data)

    @freeze_time("2023-03-10")
    def test_edit_without_nir_information(self):
        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields()
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

    def test_edit_existing_nir(self):
        other_jobseeker = JobSeekerFactory()

        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": other_jobseeker.jobseeker_profile.nir,
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur")

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == ""

    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_sso(self, _mock):
        user = JobSeekerFactory(
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            first_name="Not Bob",
            last_name="Not Saint Clar",
            birthdate=date(1970, 1, 1),
        )
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertContains(response, self.EMAIL_LABEL)

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot update data retreived from the SSO here.
        assert user.first_name != post_data["first_name"]
        assert user.last_name != post_data["last_name"]
        assert user.birthdate.strftime("%d/%m/%Y") != post_data["birthdate"]
        assert user.email != post_data["email"]

    def test_edit_without_title(self):
        MISSING_INFOS_WARNING_ID = "missing-infos-warning"
        user = JobSeekerFactory(with_address=True, title="", phone="", address_line_1="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        # No phone and no title and no address
        response = self.client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert str(warning_text) == self.snapshot(name="missing title warning with phone and address")

        # Phone but no title and no birthdate
        user.phone = "0123456789"
        user.address_line_1 = "123 rue de"
        user.birthdate = None
        user.save(
            update_fields=(
                "address_line_1",
                "birthdate",
                "phone",
            )
        )
        response = self.client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert str(warning_text) == self.snapshot(name="missing title warning without phone and with birthdate")

        # No phone but title
        user.phone = ""
        user.title = Title.MME
        user.save(update_fields=("phone", "title"))
        response = self.client.get(url)
        self.assertNotContains(response, MISSING_INFOS_WARNING_ID)

    def test_edit_with_invalid_pole_emploi_id(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        post_data = {
            "email": user.email,
            "title": user.title,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": "20/12/1978",
            "phone": user.phone,
            "pole_emploi_id": "trop long",
            "lack_of_pole_emploi_id_reason": "",
            "address_line_1": "10 rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["form"],
            "pole_emploi_id",
            "Assurez-vous que cette valeur comporte au plus 8 caractères (actuellement 9).",
        )
        self.assertFormError(
            response.context["form"],
            None,
            "Renseignez soit un identifiant France Travail, soit la raison de son absence.",
        )
        post_data["pole_emploi_id"] = "invalide"  # No length issue but validate_pole_emploi_id shouldn't be happy
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["form"],
            "pole_emploi_id",
            (
                "L'identifiant France Travail doit être composé de 8 caractères : "
                "7 chiffres suivis d'une 1 lettre ou d'un chiffre."
            ),
        )

    def test_edit_as_prescriber(self):
        original_user = PrescriberFactory(
            email="bob@saintclair.tld", first_name="Not Bob", last_name="Not Saint Clair", phone="0600000000"
        )
        self.client.force_login(original_user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertNotContains(response, self.NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        self.assertNotContains(response, self.BIRTHDATE_FIELD_NAME)
        self.assertContains(response, f"Prénom : <strong>{original_user.first_name.title()}</strong>")
        self.assertContains(response, f"Nom : <strong>{original_user.last_name.upper()}</strong>")
        self.assertContains(response, f"Adresse e-mail : <strong>{original_user.email}</strong>")
        self.assertContains(response, "Modifier ces informations")

        post_data = {
            "email": "notbob@notsaintclair.com",
            "first_name": "Bob",
            "last_name": "Saint Clair",
            "phone": "0610203050",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        updated_user = User.objects.get(pk=original_user.pk)
        assert updated_user.email == original_user.email
        assert updated_user.first_name == original_user.first_name
        assert updated_user.last_name == original_user.last_name
        assert updated_user.phone == post_data["phone"]
