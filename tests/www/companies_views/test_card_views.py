import pytest
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils.html import escape

from itou.companies.enums import ContractType
from itou.jobs.models import Appellation
from itou.utils.urls import add_url_params
from tests.cities.factories import create_city_vannes
from tests.companies.factories import (
    CompanyFactory,
    CompanyWithMembershipAndJobsFactory,
    JobDescriptionFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase, assert_previous_step, parse_response_to_soup


@pytest.mark.ignore_unknown_variable_template_error("matomo_event_attrs")
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
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        soup = parse_response_to_soup(response, selector="#main")
        assert str(soup) == self.snapshot()

    def test_card_tally_url_with_user(self):
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        user = JobSeekerFactory(pk=10)
        self.client.force_login(user)
        response = self.client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert str(soup) == self.snapshot()

    def test_card_tally_url_no_user(self):
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
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

    def test_card_flow(self):
        company = CompanyFactory(with_jobs=True)
        list_url = reverse("search:employers_results")
        company_card_base_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        company_card_initial_url = add_url_params(
            company_card_base_url,
            {"back_url": list_url},
        )
        response = self.client.get(company_card_initial_url)
        assert_previous_step(response, list_url, back_to_list=True)

        # Has link to job description
        job = company.job_description_through.first()
        job_description_link = f"{job.get_absolute_url()}?back_url={urlencode(list_url)}"
        self.assertContains(response, job_description_link)

        # Job description card has link back to list again
        response = self.client.get(job_description_link)
        assert_previous_step(response, list_url, back_to_list=True)
        # And also a link to the company card with a return link to list_url (the same as the first visited page)
        company_card_url_other_formatting = f"{company_card_base_url}?back_url={urlencode(list_url)}"
        self.assertContains(response, company_card_url_other_formatting)


@pytest.mark.ignore_unknown_variable_template_error("matomo_event_attrs")
@pytest.mark.usefixtures("unittest_compatibility")
class JobDescriptionCardViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        create_test_romes_and_appellations(["N1101"])

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

        response = self.client.get(add_url_params(url, {"back_url": reverse("companies_views:job_description_list")}))
        assert_previous_step(response, reverse("companies_views:job_description_list"), back_to_list=True)

    def test_card_tally_url_with_user(self):
        job_description = JobDescriptionFactory(
            pk=42,
            company__pk=100,
            company__for_snapshot=True,
        )
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        self.client.force_login(JobSeekerFactory(pk=10))
        response = self.client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert str(soup) == self.snapshot()

    def test_card_tally_url_no_user(self):
        job_description = JobDescriptionFactory(
            pk=42,
            company__pk=100,
            company__for_snapshot=True,
        )
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = self.client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert str(soup) == self.snapshot()
