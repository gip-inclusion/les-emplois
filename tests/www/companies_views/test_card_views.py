from urllib.parse import quote

import pytest
from django.template.defaultfilters import urlencode
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import ContractType
from itou.jobs.models import Appellation
from itou.utils.urls import add_url_params
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyWithMembershipAndJobsFactory, JobDescriptionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestCardView:
    OTHER_TAB_ID = "autres-metiers"
    APPLY = "Postuler"
    SPONTANEOUS_APPLICATIONS_OPEN = "Cet employeur accepte de recevoir des candidatures spontanées."
    SPONTANEOUS_APPLICATIONS_CLOSED = "Cet employeur n’a pas de recrutement en cours."

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        self.vannes = create_city_vannes()

    def test_card(self, client):
        company = CompanyFactory(with_membership=True)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)
        assert response.context["siae"] == company
        assertContains(response, escape(company.display_name))
        assertContains(response, company.email)
        assertContains(response, company.phone)
        assertNotContains(response, self.OTHER_TAB_ID)
        assertContains(response, self.APPLY)

    def test_card_no_active_members(self, client, snapshot):
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)
        soup = parse_response_to_soup(response, selector="#main")
        assert pretty_indented(soup) == snapshot()

    def test_card_tally_url_with_user(self, client, snapshot):
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        user = JobSeekerFactory(pk=10)
        client.force_login(user)
        response = client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert pretty_indented(soup) == snapshot()

    def test_card_tally_url_no_user(self, client, snapshot):
        company = CompanyFactory(with_membership=False, for_snapshot=True, pk=100)
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert pretty_indented(soup) == snapshot()

    def test_card_no_active_jobs(self, client, snapshot):
        company = CompanyFactory(name="les petits jardins", with_membership=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
            is_active=False,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert pretty_indented(nav_tabs_soup) == snapshot(name="nav-tabs")

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
        assert pretty_indented(tab_content_soup) == snapshot(name="tab-content")

        assertContains(response, self.APPLY)
        assertContains(response, self.SPONTANEOUS_APPLICATIONS_OPEN)
        assertNotContains(response, self.SPONTANEOUS_APPLICATIONS_CLOSED)

    def test_card_spontaneous_applications_closed(self, client):
        # Company has no active job offers, and they are not open to spontaneous applications
        company = CompanyFactory(
            name="les petits jardins", with_membership=True, spontaneous_applications_open_since=None
        )
        JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
            is_active=False,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)
        assertNotContains(response, self.APPLY)
        assertNotContains(response, self.SPONTANEOUS_APPLICATIONS_OPEN)
        assertContains(response, self.SPONTANEOUS_APPLICATIONS_CLOSED)

    def test_card_no_other_jobs(self, client, snapshot):
        company = CompanyFactory(name="les petits jardins", with_membership=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert pretty_indented(nav_tabs_soup) == snapshot(name="nav-tabs")

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
        assert pretty_indented(tab_content_soup) == snapshot(name="tab-content")

        assertContains(response, self.APPLY)

    def test_card_active_and_other_jobs(self, client, snapshot):
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
        response = client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert pretty_indented(nav_tabs_soup) == snapshot(name="nav-tabs")

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
        assert pretty_indented(tab_content_soup) == snapshot(name="tab-content")

        assertContains(response, self.APPLY)

    def test_block_job_applications(self, client, snapshot):
        company = CompanyFactory(block_job_applications=True)
        job_description = JobDescriptionFactory(
            company=company,
            custom_name="Plaquiste",
            location=self.vannes,
            contract_type=ContractType.PERMANENT,
        )
        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(url)

        nav_tabs_soup = parse_response_to_soup(response, selector=".s-tabs-01__nav")
        assert pretty_indented(nav_tabs_soup) == snapshot(name="nav-tabs")

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
        assert pretty_indented(tab_content_soup) == snapshot(name="tab-content")

        assertNotContains(response, self.APPLY)

    def test_card_flow(self, client, snapshot):
        company = CompanyFactory(with_jobs=True)
        list_url = reverse("search:employers_results")
        company_card_base_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        company_card_initial_url = add_url_params(
            company_card_base_url,
            {"back_url": list_url},
        )
        response = client.get(company_card_initial_url)
        navinfo = parse_response_to_soup(response, selector=".c-navinfo")
        assert pretty_indented(navinfo) == snapshot(name="navinfo-company-card")

        # Has link to job description
        job = company.job_description_through.first()
        job_description_link = f"{job.get_absolute_url()}?back_url={urlencode(list_url)}"
        assertContains(response, job_description_link)

        # Job description card has link back to list again
        response = client.get(job_description_link)
        navinfo = parse_response_to_soup(response, selector=".c-navinfo")
        assert pretty_indented(navinfo) == snapshot(name="navinfo-job-description")

        # And also a link to the company card with a return link to list_url (the same as the first visited page)
        company_card_url_other_formatting = f"{company_card_base_url}?back_url={urlencode(list_url)}"
        assertContains(response, company_card_url_other_formatting)

    def test_company_card_render_markdown(self, client):
        company = CompanyFactory(
            description="*Lorem ipsum*, **bold** and [link](https://beta.gouv.fr).",
            provided_support="* list 1\n* list 2\n\n1. list 1\n2. list 2",
        )
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(company_card_url)
        attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
        assertContains(
            response,
            f'<p><em>Lorem ipsum</em>, <strong>bold</strong> and <a href="https://beta.gouv.fr" {attrs}>link</a>.</p>',
        )
        assertContains(
            response, "<ul>\n<li>list 1</li>\n<li>list 2</li>\n</ul>\n<ol>\n<li>list 1</li>\n<li>list 2</li>\n</ol>"
        )

    def test_company_card_render_markdown_forbidden_tags(self, client):
        company = CompanyFactory(
            description='# Gros titre\n<script></script>\n<span class="font-size:200px;">Gros texte</span>',
        )
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = client.get(company_card_url)
        assertContains(response, "Gros titre\n\n<p>Gros texte</p>")

    def test_card_with_job_seeker_public_id(self, client):
        """
        When applying from "Mes candidats"
        """
        company = CompanyFactory(with_membership=True)
        job_description = JobDescriptionFactory(company=company)
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_application = JobApplicationFactory(
            job_seeker__first_name="Alain",
            job_seeker__last_name="Zorro",
            job_seeker__public_id="11111111-2222-3333-4444-555566667777",
            sender=prescriber,
        )
        job_seeker_public_id = job_application.job_seeker.public_id
        BANNER_TXT = "Vous postulez actuellement pour"
        BANNER_TXT_NAME = f"{BANNER_TXT} {job_application.job_seeker.get_full_name()}"
        BANNER_TXT_MASK = f"{BANNER_TXT} A… Z…"
        EXIT_URL_EMPLOYER = reverse("apply:list_prescriptions")
        EXIT_URL_PRESCRIBER = reverse("job_seekers_views:list")

        url = (
            reverse("companies_views:card", kwargs={"siae_id": company.pk})
            + f"?job_seeker_public_id={job_seeker_public_id}"
        )

        # If anonymous user, return a 200 without the banner
        response = client.get(url)
        assert response.status_code == 200
        assertNotContains(response, BANNER_TXT)

        # # If job seeker, return a  200 without the banner
        other_job_seeker = JobSeekerFactory()
        client.force_login(other_job_seeker)
        assert response.status_code == 200
        assertNotContains(response, BANNER_TXT)

        # If prescriber but not authorized, show the alert with masked name
        unauthorized_prescriber = PrescriberFactory(membership__organization__authorized=False)
        client.force_login(unauthorized_prescriber)
        response = client.get(url)
        assertContains(response, BANNER_TXT_MASK)
        assertContains(response, EXIT_URL_PRESCRIBER)

        # If any employer, show the alert
        employer = EmployerFactory(with_company=True)
        client.force_login(employer)
        response = client.get(url)
        assertContains(response, BANNER_TXT_NAME)
        assertContains(response, EXIT_URL_EMPLOYER)

        # If authorized prescriber, show the alert
        client.force_login(prescriber)
        response = client.get(url)
        assertContains(response, BANNER_TXT_NAME)
        assertContains(response, EXIT_URL_PRESCRIBER)

        # Has link to job description with job_seeker public_id
        job_description_url_with_job_seeker_id = (
            f"{job_description.get_absolute_url()}?job_seeker_public_id={job_seeker_public_id}"
            f"&amp;back_url={quote(response.wsgi_request.get_full_path())}"
        )
        assertContains(response, job_description_url_with_job_seeker_id)

        # Has link to apply with job_seeker public_id
        apply_url_with_job_seeker_id = add_url_params(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"job_seeker_public_id": job_seeker_public_id}
        )
        assertContains(response, apply_url_with_job_seeker_id, count=2)

        # When UUID is broken in GET parameters
        broken_url = reverse("companies_views:card", kwargs={"siae_id": company.pk}) + "?job_seeker_public_id=123"
        response = client.get(broken_url)
        assert response.status_code == 404

        # When uuid is not a job_seeker one
        not_job_seeker_url = (
            reverse("companies_views:card", kwargs={"siae_id": company.pk})
            + f"?job_seeker_public_id={prescriber.public_id}"
        )
        response = client.get(not_job_seeker_url)
        assert response.status_code == 404


class TestJobDescriptionCardView:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        create_test_romes_and_appellations(["N1101"])

    def test_job_description_card(self, client, snapshot):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = company.job_description_through.first()
        job_description.description = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        job_description.open_positions = 1234
        job_description.save()
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        with assertSnapshotQueries(snapshot):
            response = client.get(url)
        assert response.context["job"] == job_description
        assert response.context["siae"] == company
        assertContains(response, job_description.description)
        assertContains(response, escape(job_description.display_name))
        assertContains(response, escape(company.display_name))
        OPEN_POSITION_TEXT = "1234 postes ouverts au recrutement"
        assertContains(response, OPEN_POSITION_TEXT)

        job_description.is_active = False
        job_description.save()
        response = client.get(url)
        assertContains(response, job_description.description)
        assertContains(response, escape(job_description.display_name))
        assertContains(response, escape(company.display_name))
        assertNotContains(response, OPEN_POSITION_TEXT)

        # Check other jobs
        assert response.context["other_active_jobs"].count() == 3
        for other_active_job in response.context["other_active_jobs"]:
            assertContains(response, other_active_job.display_name, html=True)

        response = client.get(add_url_params(url, {"back_url": reverse("companies_views:job_description_list")}))
        navinfo = parse_response_to_soup(response, selector=".c-navinfo")
        assert pretty_indented(navinfo) == snapshot(name="navinfo")

    def test_job_description_card_render_markdown(self, client):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = company.job_description_through.first()
        job_description.description = "*Lorem ipsum*, **bold** and [link](https://beta.gouv.fr)."
        job_description.profile_description = "* list 1\n* list 2\n\n1. list 1\n2. list 2"
        job_description.save()
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = client.get(url)
        attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
        assertContains(
            response,
            f'<p><em>Lorem ipsum</em>, <strong>bold</strong> and <a href="https://beta.gouv.fr" {attrs}>link</a>.</p>',
        )
        assertContains(
            response,
            "<ul>\n<li>list 1</li>\n<li>list 2</li>\n</ul>\n<ol>\n<li>list 1</li>\n<li>list 2</li>\n</ol>",
        )

    def test_job_description_card_render_markdown_links(self, client):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = company.job_description_through.first()
        job_description.description = "www.lien1.com\nhttps://lien2.com\n[test](https://lien3.com)\n[test2](lien4.bzh)\ntest@admin.com\nftp://lien5.com"
        job_description.save()
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = client.get(url)
        attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
        assertContains(
            response,
            f"""<p><a href="http://www.lien1.com" {attrs}>www.lien1.com</a><br>
<a href="https://lien2.com" {attrs}>https://lien2.com</a><br>
<a href="https://lien3.com" {attrs}>test</a><br>
<a href="https://lien4.bzh" {attrs}>test2</a><br>
<a href="mailto:test@admin.com" {attrs}>test@admin.com</a><br>
<a href="https://ftp://lien5.com" {attrs}>ftp://lien5.com</a></p>""",  # allowing only HTTP and HTTPS protocols
        )

    def test_job_description_card_render_markdown_forbidden_tags(self, client):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = company.job_description_through.first()
        job_description.description = (
            '# Gros titre\n<script></script>\n<span class="font-size:200px;">Gros texte</span>'
        )
        job_description.save()
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = client.get(url)
        assertContains(response, "Gros titre\n\n<p>Gros texte</p>")

    def test_card_tally_url_with_user(self, client, snapshot):
        job_description = JobDescriptionFactory(
            pk=42,
            company__pk=100,
            company__for_snapshot=True,
        )
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        client.force_login(JobSeekerFactory(pk=10))
        response = client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert pretty_indented(soup) == snapshot(name="without_other_jobs")
        # Create other job_description
        JobDescriptionFactory(pk=43, company=job_description.company)
        response = client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")
        assert pretty_indented(soup) == snapshot(name="with_other_jobs")
        # Check link consistency
        assert parse_response_to_soup(response, selector="#recrutements")

    def test_card_tally_url_no_user(self, client, snapshot):
        job_description = JobDescriptionFactory(
            pk=42,
            company__pk=100,
            company__for_snapshot=True,
        )
        url = reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = client.get(url)
        soup = parse_response_to_soup(response, selector=".c-box--action")

        assert pretty_indented(soup) == snapshot()

    def test_card_with_job_seeker_public_id(self, client):
        """
        When applying from "Mes candidats"
        """
        company = CompanyFactory()
        job_description = JobDescriptionFactory(company=company)
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_application = JobApplicationFactory(
            job_seeker__first_name="Alain",
            job_seeker__last_name="Zorro",
            job_seeker__public_id="11111111-2222-3333-4444-555566667777",
            sender=prescriber,
        )
        job_seeker_public_id = job_application.job_seeker.public_id
        BANNER_TXT = "Vous postulez actuellement pour"
        BANNER_TXT_NAME = f"{BANNER_TXT} {job_application.job_seeker.get_full_name()}"
        BANNER_TXT_MASK = f"{BANNER_TXT} A… Z…"
        EXIT_URL_EMPLOYER = reverse("apply:list_prescriptions")
        EXIT_URL_PRESCRIBER = reverse("job_seekers_views:list")

        url = (
            reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
            + f"?job_seeker_public_id={job_seeker_public_id}"
        )

        # If anonymous user, return a 200 without banner
        response = client.get(url)
        assert response.status_code == 200
        assertNotContains(response, BANNER_TXT)

        # If job seeker, return a 200 without banner
        other_job_seeker = JobSeekerFactory()
        client.force_login(other_job_seeker)
        response = client.get(url)
        assert response.status_code == 200
        assertNotContains(response, BANNER_TXT)

        # If prescriber but not authorized, show the alert with masked name
        unauthorized_prescriber = PrescriberFactory()
        client.force_login(unauthorized_prescriber)
        response = client.get(url)
        assertContains(response, BANNER_TXT_MASK)
        assertContains(response, EXIT_URL_PRESCRIBER)

        # If any employer, show the alert
        employer = EmployerFactory(with_company=True)
        client.force_login(employer)
        response = client.get(url)
        assertContains(response, BANNER_TXT_NAME)
        assertContains(response, EXIT_URL_EMPLOYER)

        # If authorized prescriber, show the alert
        client.force_login(prescriber)
        response = client.get(url)
        assertContains(response, BANNER_TXT_NAME)
        assertContains(response, EXIT_URL_PRESCRIBER)

        # Has link to company card with job_seeker public_id
        company_url_with_job_seeker_id = (
            f"{company.get_card_url()}?job_seeker_public_id={job_seeker_public_id}"
            f"&amp;back_url={quote(response.wsgi_request.get_full_path())}"
        )
        assertContains(response, company_url_with_job_seeker_id)

        # Has link to apply with job_seeker public_id
        apply_url_with_job_seeker_id = (
            f"{reverse('apply:start', kwargs={'company_pk': company.pk})}"
            f"?job_description_id={job_description.pk}&amp;job_seeker_public_id={job_seeker_public_id}"
        )
        assertContains(response, apply_url_with_job_seeker_id)

        # When UUID is broken in GET parameters
        broken_url = (
            reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
            + "?job_seeker_public_id=123"
        )
        response = client.get(broken_url)
        assert response.status_code == 404

        # When uuid is not a job_seeker one
        not_job_seeker_url = (
            reverse("companies_views:job_description_card", kwargs={"job_description_id": job_description.pk})
            + f"?job_seeker_public_id={prescriber.public_id}"
        )
        response = client.get(not_job_seeker_url)
        assert response.status_code == 404
