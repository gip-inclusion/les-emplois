import datetime
import math

import factory
import pytest
from allauth.account.models import EmailAddress
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertFormError, assertNotContains, assertRedirects

from itou.asp.models import Commune
from itou.cities.models import City
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId, Title
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberFactory
from tests.prescribers import factories as prescribers_factories
from tests.users.factories import PrescriberFactory
from tests.utils.test import assertSnapshotQueries


DISABLED_NIR = 'disabled aria-describedby="id_nir_helptext" id="id_nir"'


class TestEditJobSeekerInfo:
    NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.city = City.objects.create(
            name="Geispolsheim",
            slug="geispolsheim-67",
            department="67",
            coords=Point(7.644817, 48.515883),
            post_codes=["67118"],
            code_insee="67152",
        )

    @property
    def address_form_fields(self):
        return {
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_line_1": "37 B Rue du Général De Gaulle",
            "insee_code": "67152",
            "post_code": "67118",
            "fill_mode": "ban_api",
        }

    def _test_address_autocomplete(self, user, post_data):
        geocoding_data = mock_get_geocoding_data_by_ban_api_resolved(post_data["ban_api_resolved_address"])
        assert user.address_line_1 == post_data["address_line_1"]
        if post_data.get("addres_line_2"):
            assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == self.city.name
        assert math.isclose(user.latitude, geocoding_data.get("latitude"), abs_tol=1e-5)
        assert math.isclose(user.longitude, geocoding_data.get("longitude"), abs_tol=1e-5)

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_by_company_with_nir(self, client, mocker, snapshot):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__jobseeker_profile__nir="178122978200508")
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}&from_application={job_application.pk}"

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(url)
        assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                f'rel="noopener">{self.NIR_UPDATE_TALLY_LINK_LABEL}</a>'
            ),
            html=True,
        )

        birthdate = datetime.date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.first_name == post_data["first_name"]
        assert job_seeker.last_name == post_data["last_name"]
        assert job_seeker.jobseeker_profile.birthdate == birthdate
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        assert job_seeker.address_line_2 == post_data["address_line_2"]

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_company_with_lack_of_nir_reason(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="",
            job_seeker__jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = client.get(url)
        assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        assertContains(response, DISABLED_NIR)
        assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)
        assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        NEW_NIR = "1 781 22978200508"

        birthdate = datetime.date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields

        response = client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_company_without_nir_information(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="", job_seeker__jobseeker_profile__lack_of_nir_reason=""
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        birthdate = datetime.date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields

        response = client.post(url, data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["lack_of_nir"] = True
        response = client.post(url, data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data.update(
            {
                "lack_of_nir": True,
                "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER.value,
            }
        )
        response = client.post(url, data=post_data)
        assertRedirects(response, expected_url=back_url)
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER
        assert job_seeker.jobseeker_profile.nir == ""

        response = client.get(url)
        assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        post_data.update(
            {
                "lack_of_nir": False,
                "nir": "1234",
            }
        )
        response = client.post(url, data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertFormError(
            response.context["form"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "1 781 22978200508"
        post_data["nir"] = NEW_NIR
        response = client.post(url, data=post_data)
        assertRedirects(response, expected_url=back_url)

        job_seeker.refresh_from_db()
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_prescriber(self, client, snapshot):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker__born_in_france=True,
        )
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        client.force_login(user)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(url)
        assert response.status_code == 200

    def test_edit_by_prescriber_of_organization(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = prescriber
        job_application.job_seeker.save()

        # Log as other member of the same organization
        other_prescriber = PrescriberFactory()
        prescribers_factories.PrescriberMembershipFactory(
            user=other_prescriber, organization=job_application.sender_prescriber_organization
        )
        client.force_login(other_prescriber)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        response = client.get(url)
        assert response.status_code == 200

    def test_edit_autonomous_not_allowed(self, client):
        job_application = JobApplicationSentByPrescriberFactory()
        # The job seeker manages his own personal information (autonomous)
        user = job_application.sender
        client.force_login(user)

        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )

        response = client.get(url)
        assert response.status_code == 403

    def test_edit_not_allowed(self, client):
        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__created_by=PrescriberFactory())

        # Lambda prescriber not member of the sender organization
        prescriber = PrescriberFactory()
        client.force_login(prescriber)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )

        response = client.get(url)
        assert response.status_code == 403

    def test_name_is_required(self, client):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_company=company, job_seeker__created_by=user)
        post_data = {
            "title": "M",
            "email": "bidou@yopmail.com",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        client.force_login(user)
        response = client.post(
            reverse(
                "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
            ),
            data=post_data,
        )
        assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_first_name">Prénom</label>
            <input type="text" name="first_name" maxlength="150" class="form-control is-invalid"
                   aria-describedby="id_first_name_error"
                   required aria-invalid="true" id="id_first_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )
        assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_last_name">Nom</label>
            <input type="text" name="last_name" maxlength="150" class="form-control is-invalid"
                   aria-describedby="id_last_name_error"
                    required aria-invalid="true" id="id_last_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_edit_email_when_unconfirmed(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        """
        The SIAE can edit the email of a jobseeker it works with, provided he did not confirm its email.
        """
        new_email = "bidou@yopmail.com"
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(
            to_company=company, job_seeker__created_by=user, job_seeker__jobseeker_profile__nir="178122978200508"
        )

        client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = client.get(url)
        assertContains(response, self.EMAIL_LABEL)

        birthdate = datetime.date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.email == new_email

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    def test_edit_email_when_confirmed(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        new_email = "bidou@yopmail.com"
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__jobseeker_profile__nir="178122978200508")
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        # Confirm job seeker email
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        EmailAddress.objects.create(user=job_seeker, email=job_seeker.email, verified=True)

        # Now the SIAE wants to edit the jobseeker email. The field is not available, and it cannot be bypassed
        client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = client.get(url)
        assertNotContains(response, self.EMAIL_LABEL)

        birthdate = datetime.date(1978, 12, 20)
        birth_place = Commune.objects.by_insee_code_and_period(self.city.code_insee, birthdate)
        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": birthdate.isoformat(),
            "birth_place": birth_place.pk,
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        # The email is not changed, but other fields are taken into account
        assert job_seeker.email != new_email
        assert job_seeker.jobseeker_profile.birthdate == birthdate
        assert job_seeker.address_line_1 == post_data["address_line_1"]
        assert job_seeker.post_code == post_data["post_code"]
        assert job_seeker.city == self.city.name

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    def test_edit_no_address_does_not_crash(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        client.force_login(user)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        post_data = {
            "title": "M",
            "email": user.email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = client.post(url, data=post_data)
        assertContains(response, "Ce champ est obligatoire.")
        assert response.context["form"].errors["address_for_autocomplete"] == ["Ce champ est obligatoire."]

    def test_fields_readonly_with_certified_criteria(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
            eligibility_diagnosis__job_seeker__created_by=factory.SelfAttribute("..author"),
            eligibility_diagnosis__job_seeker__title=Title.M,
            eligibility_diagnosis__job_seeker__jobseeker_profile__nir="178121111111151",
            eligibility_diagnosis__job_seeker__certifiable=True,
            eligibility_diagnosis__job_seeker__jobseeker_profile__birthdate=datetime.date(1978, 12, 1),
            certified=True,
        )
        job_seeker = selected_criteria.eligibility_diagnosis.job_seeker

        client.force_login(selected_criteria.eligibility_diagnosis.author)
        new_birthdate = datetime.date(1978, 12, 20)
        response = client.post(
            reverse(
                "dashboard:edit_job_seeker_info",
                kwargs={"job_seeker_public_id": job_seeker.public_id},
            ),
            {
                "title": "M",
                "first_name": "Manuel",
                "last_name": "Calavera",
                "email": job_seeker.email,
                "birthdate": new_birthdate.isoformat(),
                "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
                "birth_place": (
                    Commune.objects.filter(start_date__lte=new_birthdate, end_date__gte=new_birthdate).first().pk
                ),
                **self.address_form_fields,
            },
        )

        assertRedirects(response, reverse("dashboard:index"))
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        for attr in ["title", "first_name", "last_name"]:
            assert getattr(refreshed_job_seeker, attr) == getattr(job_seeker, attr)
        for attr in ["birthdate", "birth_place", "birth_country"]:
            assert getattr(refreshed_job_seeker.jobseeker_profile, attr) == getattr(job_seeker.jobseeker_profile, attr)
