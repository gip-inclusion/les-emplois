import math
from unittest import mock

from allauth.account.models import EmailAddress
from django.contrib.gis.geos import Point
from django.test import override_settings
from django.urls import reverse

from itou.cities.models import City
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from tests.companies.factories import (
    CompanyFactory,
)
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberFactory
from tests.prescribers import factories as prescribers_factories
from tests.users.factories import (
    PrescriberFactory,
)
from tests.utils.test import BASE_NUM_QUERIES, TestCase


DISABLED_NIR = 'disabled aria-describedby="id_nir_helptext" id="id_nir"'


class EditJobSeekerInfo(TestCase):
    NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"

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
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_with_nir(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}&from_application={job_application.pk}"

        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT companies_companymembership
        # 4.  SELECT companies_company
        # END of middlewares
        # 5.  SAVEPOINT
        # 6.  SELECT users_user
        # 7.  SELECT EXISTS account_emailaddress (verified)
        # 8.  SELECT companies_siaeconvention (menu checks for financial annexes)
        # 9.  SELECT EXISTS users_user (menu checks for active admin)
        # 10. RELEASE SAVEPOINT
        # 11. SAVEPOINT
        # 12. UPDATE django_session
        # 13. RELEASE SAVEPOINT
        with self.assertNumQueries(13):
            response = self.client.get(url)
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                f'rel="noopener">{self.NIR_UPDATE_TALLY_LINK_LABEL}</a>'
            ),
            html=True,
        )

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.first_name == post_data["first_name"]
        assert job_seeker.last_name == post_data["last_name"]
        assert job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        assert job_seeker.address_line_2 == post_data["address_line_2"]

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_with_lack_of_nir_reason(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="",
            job_seeker__jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertContains(response, DISABLED_NIR)
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)
        self.assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_without_nir_information(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="", job_seeker__jobseeker_profile__lack_of_nir_reason=""
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

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
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["lack_of_nir"] = True
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data.update(
            {
                "lack_of_nir": True,
                "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER.value,
            }
        )
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, expected_url=back_url)
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER
        assert job_seeker.jobseeker_profile.nir == ""

        response = self.client.get(url)
        self.assertContains(response, "Pour ajouter le numéro de sécurité sociale, veuillez décocher la case")

        post_data.update(
            {
                "lack_of_nir": False,
                "nir": "1234",
            }
        )
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertFormError(
            response.context["form"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "1 970 13625838386"
        post_data["nir"] = NEW_NIR
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, expected_url=back_url)

        job_seeker.refresh_from_db()
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_prescriber(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # session
            + 2  # user, memberships (ItouCurrentOrganizationMiddleware)
            + 1  # job seeker infos (get_object_or_404)
            + 1  # prescribers_prescribermembership (can_edit_personal_information/is_prescriber_with_authorized_org)
            + 1  # account_emailaddress (can_edit_email/has_verified_email)
            + 3  # update session with savepoint & release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_edit_by_prescriber_of_organization(self):
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
        self.client.force_login(other_prescriber)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        response = self.client.get(url)
        assert response.status_code == 200

    def test_edit_autonomous_not_allowed(self):
        job_application = JobApplicationSentByPrescriberFactory()
        # The job seeker manages his own personal information (autonomous)
        user = job_application.sender
        self.client.force_login(user)

        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )

        response = self.client.get(url)
        assert response.status_code == 403

    def test_edit_not_allowed(self):
        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__created_by=PrescriberFactory())

        # Lambda prescriber not member of the sender organization
        prescriber = PrescriberFactory()
        self.client.force_login(prescriber)
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )

        response = self.client.get(url)
        assert response.status_code == 403

    def test_name_is_required(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_company=company, job_seeker__created_by=user)
        post_data = {
            "title": "M",
            "email": "bidou@yopmail.com",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
            ),
            data=post_data,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_first_name">Prénom</label>
            <input type="text" name="first_name" maxlength="150" class="form-control is-invalid"
                   placeholder="Prénom" required aria-invalid="true" id="id_first_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_last_name">Nom</label>
            <input type="text" name="last_name" maxlength="150" class="form-control is-invalid"
                   placeholder="Nom" required aria-invalid="true" id="id_last_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_email_when_unconfirmed(self, _mock):
        """
        The SIAE can edit the email of a jobseeker it works with, provided he did not confirm its email.
        """
        new_email = "bidou@yopmail.com"
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_company=company, job_seeker__created_by=user)

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, self.EMAIL_LABEL)

        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.email == new_email

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_email_when_confirmed(self, _mock):
        new_email = "bidou@yopmail.com"
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        # Confirm job seeker email
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        EmailAddress.objects.create(user=job_seeker, email=job_seeker.email, verified=True)

        # Now the SIAE wants to edit the jobseeker email. The field is not available, and it cannot be bypassed
        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertNotContains(response, self.EMAIL_LABEL)

        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        # The email is not changed, but other fields are taken into account
        assert job_seeker.email != new_email
        assert job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert job_seeker.address_line_1 == post_data["address_line_1"]
        assert job_seeker.post_code == post_data["post_code"]
        assert job_seeker.city == self.city.name

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    def test_edit_no_address_does_not_crash(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
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
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Ce champ est obligatoire.")
        assert response.context["form"].errors["address_for_autocomplete"] == ["Ce champ est obligatoire."]
