from unittest import mock

from django.urls import reverse

from itou.companies.models import Company
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from tests.companies.factories import (
    CompanyFactory,
)
from tests.utils.test import TestCase


class EditCompanyViewTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_edit(self, _unused_mock):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:edit_company_step_contact_infos")
        response = self.client.get(url)
        self.assertContains(response, "Informations générales")

        post_data = {
            "brand": "NEW FAMOUS COMPANY BRAND NAME",
            "phone": "0610203050",
            "email": "",
            "website": "https://famous-company.com",
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "post_code": "62000",
            "city": "Arras",
        }
        response = self.client.post(url, data=post_data)

        # Ensure form validation is done
        self.assertContains(response, "Ce champ est obligatoire")

        # Go to next step: description
        post_data["email"] = "toto@titi.fr"
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("companies_views:edit_company_step_description"))

        response = self.client.post(url, data=post_data, follow=True)
        self.assertContains(response, "Présentation de l'activité")

        # Go to next step: summary
        url = response.redirect_chain[-1][0]
        post_data = {
            "description": "Le meilleur des SIAEs !",
            "provided_support": "On est très très forts pour tout",
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("companies_views:edit_company_step_preview"))

        response = self.client.post(url, data=post_data, follow=True)
        self.assertContains(response, "Aperçu de la fiche")

        # Go back, should not be an issue
        step_2_url = reverse("companies_views:edit_company_step_description")
        response = self.client.get(step_2_url)
        self.assertContains(response, "Présentation de l'activité")
        assert self.client.session["edit_siae_session_key"] == {
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "brand": "NEW FAMOUS COMPANY BRAND NAME",
            "city": "Arras",
            "department": "62",
            "description": "Le meilleur des SIAEs !",
            "email": "toto@titi.fr",
            "phone": "0610203050",
            "post_code": "62000",
            "provided_support": "On est très très forts pour tout",
            "website": "https://famous-company.com",
        }

        # Go forward again
        response = self.client.post(step_2_url, data=post_data, follow=True)
        self.assertContains(response, "Aperçu de la fiche")
        self.assertContains(response, "On est très très forts pour tout")

        # Save the object for real
        response = self.client.post(response.redirect_chain[-1][0])
        self.assertRedirects(response, reverse("dashboard:index"))

        # refresh company, but using the siret to be sure we didn't mess with the PK
        company = Company.objects.get(siret=company.siret)

        assert company.brand == "NEW FAMOUS COMPANY BRAND NAME"
        assert company.description == "Le meilleur des SIAEs !"
        assert company.email == "toto@titi.fr"
        assert company.phone == "0610203050"
        assert company.website == "https://famous-company.com"

        assert company.address_line_1 == "1 Rue Jeanne d'Arc"
        assert company.address_line_2 == ""
        assert company.post_code == "62000"
        assert company.city == "Arras"
        assert company.department == "62"

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        assert company.coords == "SRID=4326;POINT (2.316754 48.838411)"
        assert company.latitude == 48.838411
        assert company.longitude == 2.316754
        assert company.geocoding_score == 0.5197687103594081

    def test_permission(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        # Only admin members should be allowed to edit company's details
        membership = user.companymembership_set.first()
        membership.is_admin = False
        membership.save()
        url = reverse("companies_views:edit_company_step_contact_infos")
        response = self.client.get(url)
        assert response.status_code == 403


class EditCompanyViewWithWrongAddressTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    def test_edit(self, _unused_mock):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:edit_company_step_contact_infos")
        response = self.client.get(url)
        self.assertContains(response, "Informations générales")

        post_data = {
            "brand": "NEW FAMOUS COMPANY BRAND NAME",
            "phone": "0610203050",
            "email": "toto@titi.fr",
            "website": "https://famous-company.com",
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "post_code": "62000",
            "city": "Arras",
        }
        response = self.client.post(url, data=post_data, follow=True)

        self.assertRedirects(response, reverse("companies_views:edit_company_step_description"))

        # Go to next step: summary
        url = response.redirect_chain[-1][0]
        post_data = {
            "description": "Le meilleur des SIAEs !",
            "provided_support": "On est très très forts pour tout",
        }
        response = self.client.post(url, data=post_data, follow=True)
        self.assertRedirects(response, reverse("companies_views:edit_company_step_preview"))

        # Save the object for real
        response = self.client.post(response.redirect_chain[-1][0])
        self.assertContains(response, "L'adresse semble erronée")
