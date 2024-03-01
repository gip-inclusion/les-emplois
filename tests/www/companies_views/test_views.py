import random
from unittest import mock

import freezegun
import httpcore
import pytest
from django.core import mail
from django.core.cache import caches
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import escape

from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.jobs.models import Appellation
from itou.utils import constants as global_constants
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from itou.www.companies_views import views
from tests.cities.factories import create_city_vannes
from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyWith2MembershipsFactory,
    CompanyWithMembershipAndJobsFactory,
    JobDescriptionFactory,
    SiaeConventionFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase, parse_response_to_soup


@pytest.mark.usefixtures("unittest_compatibility")
class CardViewTest(TestCase):
    OTHER_TAB_ID = "autres-metiers"
    APPLY = "Postuler"

    @classmethod
    def setUpTestData(cls):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        cls.vannes = create_city_vannes()

    def test_card(self):
        company = CompanyFactory(with_membership=True)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        assert response.context["siae"] == company
        self.assertContains(response, escape(company.display_name))
        self.assertContains(response, company.email)
        self.assertContains(response, company.phone)
        self.assertNotContains(response, self.OTHER_TAB_ID)
        self.assertContains(response, self.APPLY)

    def test_card_no_active_members(self):
        company = CompanyFactory(with_membership=False, for_snapshot=True)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        soup = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/apply/{company.pk}/start", "/apply/[PK of Company]/start"),
                ("data-it-copy-to-clipboard", f"/company/{company.pk}/card", "/company/[PK of Company]/card"),
            ],
        )
        assert str(soup) == self.snapshot()

    def test_card_no_active_jobs(self):
        company = CompanyFactory(name="les petits jardins", with_membership=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
            is_active=False,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert str(nav_tabs_soup) == self.snapshot(name="nav-tabs")

        tab_content_soup = parse_response_to_soup(
            response,
            selector=".tab-content",
            replace_in_attr=[
                (
                    "href",
                    f"/company/job_description/{job_description.pk}/card",
                    "/company/job_description/[PK of JobDescription]/card",
                ),
                ("href", f"?back_url=/company/{company.pk}/card", "?back_url=/company/[PK of Company]/card"),
                ("href", f"/apply/{company.pk}/start", "/apply/[PK of Company]/start"),
            ],
        )
        assert str(tab_content_soup) == self.snapshot(name="tab-content")

        self.assertContains(response, self.APPLY)

    def test_card_no_other_jobs(self):
        company = CompanyFactory(name="les petits jardins", with_membership=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert str(nav_tabs_soup) == self.snapshot(name="nav-tabs")

        tab_content_soup = parse_response_to_soup(
            response,
            selector=".tab-content",
            replace_in_attr=[
                (
                    "href",
                    f"/company/job_description/{job_description.pk}/card",
                    "/company/job_description/[PK of JobDescription]/card",
                ),
                ("href", f"?back_url=/company/{company.pk}/card", "?back_url=/company/[PK of Company]/card"),
                ("href", f"/apply/{company.pk}/start", "/apply/[PK of Company]/start"),
            ],
        )
        assert str(tab_content_soup) == self.snapshot(name="tab-content")

        self.assertContains(response, self.APPLY)

    def test_card_active_and_other_jobs(self):
        company = CompanyFactory(name="les petits jardins", with_membership=True)
        # Job appellation must be different, the factory picks one at random.
        app1, app2 = Appellation.objects.filter(code__in=["12001", "12007"]).order_by("code")
        active_job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
            appellation=app1,
        )
        other_job_description = JobDescriptionFactory(
            company=company,
            custom_name="Peintre",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
            appellation=app2,
            is_active=False,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert str(nav_tabs_soup) == self.snapshot(name="nav-tabs")

        tab_content_soup = parse_response_to_soup(
            response,
            selector=".tab-content",
            replace_in_attr=[
                (
                    "href",
                    f"/company/job_description/{active_job_description.pk}/card",
                    "/company/job_description/[PK of JobDescription]/card",
                ),
                (
                    "href",
                    f"/company/job_description/{other_job_description.pk}/card",
                    "/company/job_description/[PK of JobDescription]/card",
                ),
                ("href", f"?back_url=/company/{company.pk}/card", "?back_url=/company/[PK of Company]/card"),
                ("href", f"/apply/{company.pk}/start", "/apply/[PK of Company]/start"),
            ],
        )
        assert str(tab_content_soup) == self.snapshot(name="tab-content")

        self.assertContains(response, self.APPLY)

    def test_block_job_applications(self):
        company = CompanyFactory(block_job_applications=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert str(nav_tabs_soup) == self.snapshot(name="nav-tabs")

        tab_content_soup = parse_response_to_soup(
            response,
            selector=".tab-content",
            replace_in_attr=[
                (
                    "href",
                    f"/company/job_description/{job_description.pk}/card",
                    "/company/job_description/[PK of JobDescription]/card",
                ),
                ("href", f"?back_url=/company/{company.pk}/card", "?back_url=/company/[PK of Company]/card"),
                ("href", f"/apply/{company.pk}/start", "/apply/[PK of Company]/start"),
            ],
        )
        assert str(tab_content_soup) == self.snapshot(name="tab-content")

        self.assertNotContains(response, self.APPLY)


class JobDescriptionCardViewTest(TestCase):
    def test_job_description_card(self):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = company.job_description_through.first()
        job_description.description = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        job_description.open_positions = 1234
        job_description.save()
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select jobdescription (get_object_or_404)
            + 1  # select other jobdescription (others_active_jobs)
        ):
            response = self.client.get(url)
        assert response.context["job"] == job_description
        assert response.context["siae"] == company
        self.assertContains(response, job_description.description)
        self.assertContains(response, escape(job_description.display_name))
        self.assertContains(response, escape(company.display_name))
        OPEN_POSITION_TEXT = "1234 postes ouverts au recrutement"
        self.assertContains(response, OPEN_POSITION_TEXT)

        job_description.is_active = False
        job_description.save()
        response = self.client.get(url)
        self.assertContains(response, job_description.description)
        self.assertContains(response, escape(job_description.display_name))
        self.assertContains(response, escape(company.display_name))
        self.assertNotContains(response, OPEN_POSITION_TEXT)

        # Check other jobs
        assert response.context["others_active_jobs"].count() == 3
        for other_active_job in response.context["others_active_jobs"]:
            self.assertContains(response, other_active_job.display_name, html=True)


class ShowAndSelectFinancialAnnexTest(TestCase):
    def test_asp_source_siae_admin_can_see_but_cannot_select_af(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_ASP

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 403

    def test_user_created_siae_admin_can_see_and_select_af(self):
        company = CompanyFactory(
            source=Company.SOURCE_USER_CREATED,
            with_membership=True,
        )
        user = company.members.first()
        old_convention = company.convention
        # Only conventions of the same SIREN can be selected.
        new_convention = SiaeConventionFactory(siret_signature=f"{company.siren}12345")

        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_USER_CREATED

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 200

        assert company.convention == old_convention
        assert company.convention != new_convention

        post_data = {
            "financial_annexes": new_convention.financial_annexes.get().id,
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        company.refresh_from_db()
        assert company.convention != old_convention
        assert company.convention == new_convention

    def test_staff_created_siae_admin_cannot_see_nor_select_af(self):
        company = CompanyFactory(source=Company.SOURCE_STAFF_CREATED, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_STAFF_CREATED

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 403

    def test_asp_source_siae_non_admin_cannot_see_nor_select_af(self):
        company = CompanyFactory(with_membership=True)
        user = EmployerFactory()
        company.members.add(user)
        assert not company.has_admin(user)
        assert company.should_have_convention
        assert company.source == Company.SOURCE_ASP

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 403

    def test_import_created_geiq_admin_cannot_see_nor_select_af(self):
        company = CompanyFactory(kind=CompanyKind.GEIQ, source=Company.SOURCE_GEIQ, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert not company.should_have_convention
        assert company.source == Company.SOURCE_GEIQ

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 403

    def test_user_created_geiq_admin_cannot_see_nor_select_af(self):
        company = CompanyFactory(kind=CompanyKind.GEIQ, source=Company.SOURCE_USER_CREATED, with_membership=True)
        user = company.members.first()
        assert company.has_admin(user)
        assert not company.should_have_convention
        assert company.source == Company.SOURCE_USER_CREATED

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        url = reverse("companies_views:show_financial_annexes")
        response = self.client.get(url)
        assert response.status_code == 403
        url = reverse("companies_views:select_financial_annex")
        response = self.client.get(url)
        assert response.status_code == 403


class CreateCompanyViewTest(TestCase):
    STRUCTURE_ALREADY_EXISTS_MSG = escape("La structure à laquelle vous souhaitez vous rattacher est déjà")

    @staticmethod
    def siret_siren_error_msg(company):
        return escape(f"Le SIRET doit commencer par le SIREN {company.siren}")

    def test_create_non_preexisting_company_outside_of_siren_fails(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        new_siren = "9876543210"
        new_siret = f"{new_siren}1234"
        assert company.siren != new_siren
        assert not Company.objects.filter(siret=new_siret).exists()

        post_data = {
            "siret": new_siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)

        self.assertContains(response, self.siret_siren_error_msg(company))
        self.assertNotContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)

        assert not Company.objects.filter(siret=post_data["siret"]).exists()

    def test_create_preexisting_company_outside_of_siren_fails(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        preexisting_company = CompanyFactory()
        new_siret = preexisting_company.siret
        assert company.siren != preexisting_company.siren
        assert Company.objects.filter(siret=new_siret).exists()

        post_data = {
            "siret": new_siret,
            "kind": preexisting_company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)

        self.assertNotContains(response, self.siret_siren_error_msg(company))
        self.assertContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    def test_cannot_create_company_with_same_siret_and_same_kind(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": company.siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)

        self.assertNotContains(response, self.siret_siren_error_msg(company))
        self.assertContains(response, self.STRUCTURE_ALREADY_EXISTS_MSG)
        self.assertContains(response, escape(global_constants.ITOU_HELP_CENTER_URL))

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_cannot_create_company_with_same_siret_and_different_kind(self, _mock_call_ban_geocoding_api):
        company = CompanyFactory(with_membership=True)
        company.kind = CompanyKind.ETTI
        company.save()
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": company.siret,
            "kind": CompanyKind.ACI,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200

        assert Company.objects.filter(siret=post_data["siret"]).count() == 1

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_cannot_create_company_with_same_siren_and_different_kind(self, _mock_call_ban_geocoding_api):
        company = CompanyFactory(with_membership=True)
        company.kind = CompanyKind.ETTI
        company.save()
        user = company.members.first()

        new_siret = company.siren + "12345"
        assert company.siret != new_siret

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {
            "siret": new_siret,
            "kind": CompanyKind.ACI,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200

        assert Company.objects.filter(siret=company.siret).count() == 1
        assert Company.objects.filter(siret=new_siret).count() == 0

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_company_with_same_siren_and_same_kind(self, mock_call_ban_geocoding_api):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        self.client.force_login(user)

        url = reverse("companies_views:create_company")
        response = self.client.get(url)
        assert response.status_code == 200

        new_siret = company.siren + "12345"
        assert company.siret != new_siret

        post_data = {
            "siret": new_siret,
            "kind": company.kind,
            "name": "FAMOUS COMPANY SUB STRUCTURE",
            "source": Company.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        mock_call_ban_geocoding_api.assert_called_once()

        new_company = Company.objects.get(siret=new_siret)
        assert new_company.has_admin(user)
        assert company.source == Company.SOURCE_ASP
        assert new_company.source == Company.SOURCE_USER_CREATED
        assert new_company.siret == post_data["siret"]
        assert new_company.kind == post_data["kind"]
        assert new_company.name == post_data["name"]
        assert new_company.address_line_1 == post_data["address_line_1"]
        assert new_company.city == post_data["city"]
        assert new_company.post_code == post_data["post_code"]
        assert new_company.department == post_data["department"]
        assert new_company.email == post_data["email"]
        assert new_company.phone == post_data["phone"]
        assert new_company.website == post_data["website"]
        assert new_company.description == post_data["description"]
        assert new_company.created_by == user
        assert new_company.source == Company.SOURCE_USER_CREATED
        assert new_company.is_active
        assert new_company.convention is not None
        assert company.convention == new_company.convention

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        assert new_company.coords == "SRID=4326;POINT (2.316754 48.838411)"
        assert new_company.latitude == 48.838411
        assert new_company.longitude == 2.316754
        assert new_company.geocoding_score == 0.587663373207207


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
        assert company.geocoding_score == 0.587663373207207

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


class MembersTest(TestCase):
    MORE_ADMIN_MSG = "Nous vous recommandons de nommer plusieurs administrateurs"

    def test_members(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)
        url = reverse("companies_views:members")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_active_members(self):
        company = CompanyFactory()
        active_member_active_user = CompanyMembershipFactory(company=company)
        active_member_inactive_user = CompanyMembershipFactory(company=company, user__is_active=False)
        inactive_member_active_user = CompanyMembershipFactory(company=company, is_active=False)
        inactive_member_inactive_user = CompanyMembershipFactory(
            company=company, is_active=False, user__is_active=False
        )

        self.client.force_login(active_member_active_user.user)
        url = reverse("companies_views:members")
        response = self.client.get(url)
        assert response.status_code == 200
        assert len(response.context["members"]) == 1
        assert active_member_active_user in response.context["members"]
        assert active_member_inactive_user not in response.context["members"]
        assert inactive_member_active_user not in response.context["members"]
        assert inactive_member_inactive_user not in response.context["members"]

    def test_members_admin_warning_one_user(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)
        url = reverse("companies_views:members")
        response = self.client.get(url)
        self.assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_two_users(self):
        company = CompanyWith2MembershipsFactory()
        user = company.members.first()
        self.client.force_login(user)
        url = reverse("companies_views:members")
        response = self.client.get(url)
        self.assertContains(response, self.MORE_ADMIN_MSG)

        # Set all users admins
        company.memberships.update(is_admin=True)
        response = self.client.get(url)
        self.assertNotContains(response, self.MORE_ADMIN_MSG)

    def test_members_admin_warning_many_users(self):
        company = CompanyWith2MembershipsFactory()
        CompanyMembershipFactory(company=company, user__is_active=False)
        CompanyMembershipFactory(company=company, is_admin=False, user__is_active=False)
        user = company.members.first()
        self.client.force_login(user)
        url = reverse("companies_views:members")
        response = self.client.get(url)
        self.assertContains(response, self.MORE_ADMIN_MSG)


class UserMembershipDeactivationTest(TestCase):
    def test_self_deactivation(self):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        company = CompanyFactory(with_membership=True)
        admin = company.members.filter(companymembership__is_admin=True).first()
        memberships = admin.companymembership_set.all()
        membership = memberships.first()

        self.client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": admin.id})
        response = self.client.post(url)
        assert response.status_code == 403

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        assert membership.is_active

    def test_deactivate_user(self):
        """
        Standard use case of user deactivation.
        Everything should be fine ...
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        membership = guest.companymembership_set.first()
        assert guest not in company.active_admin_members
        assert admin in company.active_admin_members

        self.client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302

        # User should be deactivated now
        membership.refresh_from_db()
        assert not membership.is_active
        assert admin == membership.updated_by
        assert membership.updated_at is not None

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert f"[Désactivation] Vous n'êtes plus membre de {company.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion" in email.body
        assert email.to[0] == guest.email

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        company = CompanyWith2MembershipsFactory()
        guest = company.members.filter(companymembership__is_admin=False).first()
        self.client.force_login(guest)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 403

    def test_user_with_no_company_left(self):
        """
        Former employer with no membership left must not be able to log in.
        They are still "active" technically speaking, so if they
        are activated/invited again, they will be able to log in.
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302
        self.client.logout()

        self.client.force_login(guest)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # should be redirected to logout
        assert response.status_code == 302
        assert response.url == reverse("account_logout")

    def test_structure_selector(self):
        """
        Check that a deactivated member can't access the structure
        from the dashboard selector
        """
        company_2 = CompanyFactory(with_membership=True)
        guest = company_2.members.first()

        company_1 = CompanyWith2MembershipsFactory()
        admin = company_1.members.first()
        company_1.members.add(guest)

        memberships = guest.companymembership_set.all()
        assert len(memberships) == 2

        # Admin remove guest from structure
        self.client.force_login(admin)
        url = reverse("companies_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        assert response.status_code == 302
        self.client.logout()

        # guest must be able to login
        self.client.force_login(guest)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # Wherever guest lands should give a 200 OK
        assert response.status_code == 200

        # Check response context, only one company should remain
        assert len(response.context["request"].organizations) == 1


class CompanyAdminMembersManagementTest(TestCase):
    def test_add_admin(self):
        """
        Check the ability for an admin to add another admin to the company
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = self.client.post(url)
        assert response.status_code == 302

        company.refresh_from_db()
        assert_set_admin_role__creation(user=guest, organization=company)

    def test_remove_admin(self):
        """
        Check the ability for an admin to remove another admin
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        membership = guest.companymembership_set.first()
        membership.is_admin = True
        membership.save()
        assert guest in company.active_admin_members

        self.client.force_login(admin)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        assert response.status_code == 200

        # Confirm action
        response = self.client.post(url)
        assert response.status_code == 302

        company.refresh_from_db()
        assert_set_admin_role__removal(user=guest, organization=company)

    def test_admin_management_permissions(self):
        """
        Non-admin users can't update admin members
        """
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        self.client.force_login(guest)
        url = reverse("companies_views:update_admin_role", kwargs={"action": "remove", "user_id": admin.id})

        # Redirection to confirm page
        response = self.client.get(url)
        assert response.status_code == 403

        # Confirm action
        response = self.client.post(url)
        assert response.status_code == 403

        # Add self as admin with no privilege
        url = reverse("companies_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        response = self.client.get(url)
        assert response.status_code == 403

        response = self.client.post(url)
        assert response.status_code == 403

    def test_suspicious_action(self):
        """
        Test "suspicious" actions: action code not registered for use (even if admin)
        """
        suspicious_action = "h4ckm3"
        company = CompanyWith2MembershipsFactory()
        admin = company.members.filter(companymembership__is_admin=True).first()
        guest = company.members.filter(companymembership__is_admin=False).first()

        self.client.force_login(guest)
        # update: less test with RE_PATH
        with pytest.raises(NoReverseMatch):
            reverse("companies_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})


def test_dora_url(settings):
    settings.DORA_BASE_URL = "https://dora.fake.gouv.fr/"
    assert views.dora_url("toto", "superb-id") == "https://dora.fake.gouv.fr/services/di--toto--superb-id"
    assert views.dora_url("dora", "superb-id") == "https://dora.fake.gouv.fr/services/di--dora--superb-id"
    assert views.dora_url("dora", "superb-id", "foobar") == "foobar"


def test_displayable_thematique():
    assert views.displayable_thematique("une-thematique-comme-ça--et-une-sous-thematique") == "UNE THEMATIQUE COMME ÇA"


def test_get_data_inclusion_services(settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": {
                        "id": "svc1",
                        "source": "dora",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["a-distance"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc1",
                    },
                    "distance": 1,
                },
                {
                    "service": {
                        "id": "svc2",
                        "source": "fake",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc2",
                    },
                    "distance": 3,
                },
                {
                    "service": {
                        "id": "svc3",
                        "source": "dora",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel", "a-distance"],
                    },
                    "distance": 2,
                },
                {
                    "service": {
                        "id": "svc4",
                        "source": "fake",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc4",
                    },
                    "distance": 5,
                },
            ]
        },
    )

    assert views.get_data_inclusion_services(None) == []
    random.seed(0)  # ensure the mock data is stable
    mocked_final_response = [
        {
            "dora_di_url": "https://dora.inclusion.beta.gouv.fr/services/di--fake--svc4",
            "id": "svc4",
            "lien_source": "https://fake.api.gouv.fr/services/svc4",
            "modes_accueil": ["en-presentiel"],
            "source": "fake",
            "thematiques": ["a--b"],
            "thematiques_display": {"A"},
        },
        {
            "dora_di_url": "https://dora.inclusion.beta.gouv.fr/services/di--fake--svc2",
            "id": "svc2",
            "lien_source": "https://fake.api.gouv.fr/services/svc2",
            "modes_accueil": ["en-presentiel"],
            "source": "fake",
            "thematiques": ["a--b"],
            "thematiques_display": {"A"},
        },
    ]
    with freezegun.freeze_time("2024-01-01") as frozen_datetime:
        # make the actual API request
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 1
        # hit the cache on the second call
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 1

        # expire the cache key
        frozen_datetime.move_to("2024-01-02")
        random.seed(0)  # ensure the mock data is stable
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 2

    with freezegun.freeze_time("2024-01-01") as frozen_datetime:
        api_mock.mock(side_effect=httpcore.TimeoutException)
        assert views.get_data_inclusion_services("89000") == []


def test_hx_dora_services(htmx_client, snapshot, settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    base_service = {
        "id": "svc1",
        "source": "dora",
        "nom": "Coupe les cheveux",
        "thematiques": ["a--b"],
        "modes_accueil": ["en-presentiel"],
        "lien_source": "https://fake.api.gouv.fr/services/svc1",
        "structure": {"nom": "Coiffeur"},
    }
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": base_service,
                    "distance": 1,
                },
            ]
        },
    )
    response = htmx_client.get(reverse("companies_views:hx_dora_services", kwargs={"code_insee": "75056"}))
    dora_service_card = parse_response_to_soup(response, selector=".card-body")
    assert str(dora_service_card) == snapshot(name="Dora service card")

    caches["failsafe"].clear()
    base_service["code_postal"] = "75056"
    base_service["commune"] = "Paris"
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": base_service.copy(),
                    "distance": 1,
                },
            ]
        },
    )

    response = htmx_client.get(reverse("companies_views:hx_dora_services", kwargs={"code_insee": "75056"}))
    dora_service_card = parse_response_to_soup(response, selector=".card-body")
    assert str(dora_service_card) == snapshot(name="Dora service card with address")
