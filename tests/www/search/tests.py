import pytest
from django.contrib.gis.geos import Point
from django.template.defaultfilters import capfirst, urlencode as urlencode_filter
from django.templatetags.static import static
from django.test import override_settings
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from django.utils.http import urlencode

from itou.cities.models import City
from itou.companies.enums import POLE_EMPLOI_SIRET, CompanyKind, ContractNature, ContractType, JobSource
from itou.companies.models import Company
from itou.jobs.models import Appellation, Rome
from tests.cities.factories import create_city_guerande, create_city_saint_andre, create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import BASE_NUM_QUERIES, TestCase, assert_previous_step, parse_response_to_soup


DISTRICTS = "Arrondissements de Paris"


class SearchCompanyTest(TestCase):
    URL = reverse_lazy("search:employers_results")
    URL_JOBS = reverse_lazy("search:job_descriptions_results")

    @pytest.mark.ignore_template_errors
    def test_not_existing(self):
        response = self.client.get(self.URL, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")
        # The optional company filter isn't visible when no result is available
        assert "company" not in response.context["form"]

    @override_settings(MATOMO_BASE_URL="https://matomo.example.com")
    def test_district(self):
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris",
            slug=city_slug,
            department="75",
            post_codes=["75001"],
            coords=Point(5, 23),
            code_insee="75056",
        )

        City.objects.create(
            name="Paris 10eme", slug="paris-10eme-75", department="75", post_codes=["75010"], coords=Point(5, 23)
        )

        company_1 = CompanyFactory(department="75", coords=paris_city.coords, post_code="75001")
        CompanyFactory(department="75", coords=paris_city.coords, post_code="75002")

        # Filter on city
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select the city
            + 1  # fetch initial companies (to extract the filters afterwards)
            + 2  # two counts for the tab headers
            + 1  # refetch the city for widget rendering
            + 1  # actual select of the companies, with related objects and annotated distance
            + 1  # prefetch active job descriptions
        ):
            response = self.client.get(self.URL, {"city": city_slug})

        self.assertContains(response, "Emplois inclusifs à 25 km du centre de Paris (75)")
        # look for the matomo_custom_title
        self.assertContains(response, "Rechercher un emploi inclusif")
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">2</span>',
            html=True,
        )
        self.assertContains(response, DISTRICTS)

        # Filter on district
        response = self.client.get(self.URL, {"city": city_slug, "districts_75": ["75001"]})
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
        )
        self.assertContains(response, company_1.display_name)

        # Do not get arrondissements when searching the arrondissement directly
        response = self.client.get(self.URL, {"city": "paris-10eme-75"})
        self.assertNotContains(response, DISTRICTS)

    def test_kind(self):
        city = create_city_saint_andre()
        CompanyFactory(department="44", coords=city.coords, post_code="44117", kind=CompanyKind.AI)

        response = self.client.get(self.URL, {"city": city.slug, "kinds": [CompanyKind.AI]})
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
            count=1,
        )

        response = self.client.get(self.URL, {"city": city.slug, "kinds": [CompanyKind.EI]})
        self.assertContains(response, "Aucun résultat")

    def test_distance(self):
        # 3 companies in two departments to test distance and department filtering
        vannes = create_city_vannes()
        COMPANY_VANNES = "Entreprise Vannes"
        CompanyFactory(
            name=COMPANY_VANNES, department="56", coords=vannes.coords, post_code="56760", kind=CompanyKind.AI
        )

        guerande = create_city_guerande()
        COMPANY_GUERANDE = "Entreprise Guérande"
        CompanyFactory(
            name=COMPANY_GUERANDE, department="44", coords=guerande.coords, post_code="44350", kind=CompanyKind.AI
        )
        saint_andre = create_city_saint_andre()
        COMPANY_SAINT_ANDRE = "Entreprise Saint André des Eaux"
        CompanyFactory(
            name=COMPANY_SAINT_ANDRE,
            department="44",
            coords=saint_andre.coords,
            post_code="44117",
            kind=CompanyKind.AI,
        )

        # 100 km
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">3</span>',
            html=True,
            count=1,
        )
        self.assertContains(response, COMPANY_VANNES.capitalize())
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 15})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">2</span>',
            html=True,
            count=1,
        )
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">2</span>',
            html=True,
            count=1,
        )
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.URL, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
        )
        self.assertContains(response, COMPANY_VANNES.capitalize())

    def test_order_by(self):
        """
        Check company results sorting.
        Don't test sorting by active members to avoid creating too much data.
        """
        guerande = create_city_guerande()
        created_companies = []

        # Several job descriptions but no job application.
        company = CompanyFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        created_companies.append(company)

        # Many job descriptions and job applications.
        company = CompanyFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_company=company)
        created_companies.append(company)

        # Many job descriptions and more job applications than the first one.
        company = CompanyFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_company=company)
        JobApplicationFactory(to_company=company)
        created_companies.append(company)

        # No job description, no job application.
        company = CompanyFactory(department="44", coords=guerande.coords, post_code="44350")
        created_companies.append(company)

        # Does not want to receive any job application.
        company = CompanyFactory(
            department="44", coords=guerande.coords, post_code="44350", block_job_applications=True
        )
        created_companies.append(company)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # find city
            + 1  # find companies
            + 1  # count companies
            + 1  # count job descriptions
            + 1  # refetch the city for widget rendering
            + 1  # get companies infos
            + 1  # get job descriptions infos
        ):
            response = self.client.get(self.URL, {"city": guerande.slug})
        companies_results = response.context["results_page"]

        assert [company.pk for company in companies_results] == [company.pk for company in created_companies]

    def test_opcs_displays_card_differently(self):
        city = create_city_saint_andre()
        CompanyFactory(department="44", coords=city.coords, post_code="44117", kind=CompanyKind.OPCS)

        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
            count=1,
        )
        self.assertContains(response, "Offres clauses sociales")

    def test_is_popular(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117", with_membership=True)
        job = JobDescriptionFactory(company=company)
        JobApplicationFactory.create_batch(19, to_company=company, selected_jobs=[job], state="new")
        response = self.client.get(self.URL, {"city": city.slug})
        popular_badge = """
            <span class="badge badge-sm rounded-pill bg-accent-03 text-primary">
                <i class="ri-group-line me-1" aria-hidden="true"></i>
                20+<span class="ms-1">candidatures</span>
            </span>
            """
        self.assertNotContains(response, popular_badge, html=True)

        JobApplicationFactory(to_company=company, selected_jobs=[job], state="new")
        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(response, popular_badge, html=True)

    def test_has_no_active_members(self):
        create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)
        no_hiring_str = (
            "Cet employeur n'est actuellement pas inscrit sur le site des emplois de l’inclusion, "
            "vous ne pouvez pas déposer de candidature en ligne"
        )
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117")
        job_description = JobDescriptionFactory(company=company)
        job_description_str = job_description.get_absolute_url()
        response = self.client.get(self.URL, {"city": city.slug})
        self.assertNotContains(response, job_description_str)
        self.assertContains(response, no_hiring_str)

        CompanyMembershipFactory(company=company)
        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(response, job_description_str)
        self.assertNotContains(response, no_hiring_str)

    def test_company(self):
        create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)
        # 3 companies in two departments to test distance and department filtering
        vannes = create_city_vannes()
        COMPANY_VANNES = "Entreprise Vannes"
        CompanyFactory(
            name=COMPANY_VANNES, department="56", coords=vannes.coords, post_code="56760", kind=CompanyKind.AI
        )

        guerande = create_city_guerande()
        COMPANY_GUERANDE = "Entreprise Guérande"
        guerande_company = CompanyFactory(
            name=COMPANY_GUERANDE,
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=CompanyKind.AI,
            with_membership=True,
        )
        job_description = JobDescriptionFactory(company=guerande_company, location=guerande)
        saint_andre = create_city_saint_andre()
        COMPANY_SAINT_ANDRE = "Entreprise Saint André des Eaux"
        CompanyFactory(
            name=COMPANY_SAINT_ANDRE,
            department="44",
            coords=saint_andre.coords,
            post_code="44117",
            kind=CompanyKind.AI,
        )

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # find city (city form field cleaning)
            + 1  # find companies (add_form_choices)
            + 1  # count companies (paginator)
            + 1  # count job descriptions (job_descriptions_count from context)
            + 1  # refetch the city for widget rendering
            + 1  # get companies infos for page
            + 1  # get job descriptions infos (prefetch with is_popular annotation)
        ):
            response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">3</span>',
            html=True,
            count=1,
        )
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # find city (city form field cleaning)
            + 1  # find companies (add_form_choices)
            + 1  # count companies (paginator)
            + 1  # count job descriptions (job_descriptions_count from context)
            + 1  # refetch the city for widget rendering
            + 1  # get companies infos for page
            + 1  # get job descriptions infos (prefetch with is_popular annotation)
        ):
            response = self.client.get(
                self.URL, {"city": guerande.slug, "distance": 100, "company": guerande_company.pk}
            )
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
            count=1,
        )
        assert_previous_step(response, reverse("search:employers_home"))

        # Has link to company card with back_url
        company_url = (
            f"{guerande_company.get_card_url()}?back_url={urlencode_filter(response.wsgi_request.get_full_path())}"
        )
        self.assertContains(response, company_url)

        # Has link to job description with back_url
        job_description_url = (
            f"{job_description.get_absolute_url()}?back_url={urlencode_filter(response.wsgi_request.get_full_path())}"
        )
        self.assertContains(response, job_description_url)

        # Check that invalid value doesn't crash
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100, "company": "foobar"})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">3</span>',
            html=True,
            count=1,
        )

    def test_htmx_reloads_departments(self):
        vannes = create_city_vannes()
        company_vannes = CompanyFactory(
            name="Entreprise Vannes", department="56", coords=vannes.coords, post_code="56760", kind=CompanyKind.AI
        )
        guerande = create_city_guerande()
        company_guerande = CompanyFactory(
            name="Entreprise Guérande", department="44", coords=guerande.coords, post_code="44350"
        )

        # Using SiaeSearchForm.DISTANCE_DEFAULT.
        response = self.client.get(self.URL, {"city": guerande.slug})
        guerande_opt = f'<option value="{company_guerande.pk}">{company_guerande.name.capitalize()}</option>'
        vannes_opt = f'<option value="{company_vannes.pk}">{company_vannes.name.capitalize()}</option>'
        self.assertContains(response, guerande_opt, html=True, count=1)
        self.assertNotContains(response, vannes_opt, html=True)
        simulated_page = parse_response_to_soup(response)

        def distance_radio(distance):
            [elt] = simulated_page.find_all("input", attrs={"name": "distance", "value": f"{distance}"})
            return elt

        distance_radio(100)["checked"] = "checked"
        del distance_radio(25)["checked"]
        response = self.client.get(
            self.URL,
            {"city": guerande.slug, "distance": 100},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{self.URL}']", response)
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)
        # Companies in the select2 were reloaded as well.
        self.assertContains(response, guerande_opt, html=True, count=1)
        self.assertContains(response, vannes_opt, html=True, count=1)


class SearchPrescriberTest(TestCase):
    def test_home(self):
        url = reverse("search:prescribers_home")
        response = self.client.get(url)
        self.assertContains(response, "Rechercher des prescripteurs habilités")

    @pytest.mark.ignore_template_errors
    def test_results(self):
        url = reverse("search:prescribers_results")

        vannes = create_city_vannes()
        guerande = create_city_guerande()
        organization_1 = PrescriberOrganizationFactory(authorized=True, coords=guerande.coords)
        PrescriberOrganizationFactory(authorized=True, coords=vannes.coords)

        response = self.client.get(url, {"city": guerande.slug, "distance": 100})
        self.assertContains(response, "2 résultats")
        assert_previous_step(response, reverse("search:prescribers_home"))

        # Has link to organization card with back_url
        organization_url = f"{organization_1.get_card_url()}?back_url={urlencode_filter(url)}"
        self.assertContains(response, organization_url)

        response = self.client.get(url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "1 résultat")


class JobDescriptionSearchViewTest(TestCase):
    URL = reverse_lazy("search:job_descriptions_results")
    URL_EMPLOYERS = reverse_lazy("search:employers_results")

    @pytest.mark.ignore_template_errors
    def test_not_existing(self):
        response = self.client.get(self.URL, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")

    def test_results(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )
        filters_param = {"city": city_slug, "city_name": "Paris (75)", "distance": 25}

        company = CompanyFactory(department="75", coords=paris_city.coords, post_code="75001")
        job = JobDescriptionFactory(company=company)

        # Filter on city
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select the city
            + 1  # fetch initial job descriptions to add to the form fields
            + 2  # count the number of results for companies & job descriptions
            + 1  # prefetch job applications for the is_popular attribute
            + 1  # refetch the city for widget rendering
            + 1  # select the job descriptions for the page
        ):
            response = self.client.get(self.URL, {"city": city_slug})

        self.assertContains(response, "Emplois inclusifs à 25 km du centre de Paris (75)")
        self.assertContains(
            response,
            f"""
            <a class="nav-link active"
                data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="clic-onglet-fichesdeposte"
                href="{self.URL}?{escape(urlencode(filters_param))}">
                <i class="ri-briefcase-4-line font-weight-normal me-1" aria-hidden="true"></i>
                <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
                <span class="badge badge-sm rounded-pill ms-2">1</span>
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a class="nav-link"
                data-matomo-event="true" data-matomo-category="candidature"
                data-matomo-action="clic" data-matomo-option="clic-onglet-employeur"
                href="{self.URL_EMPLOYERS}?{escape(urlencode(filters_param))}">
                <i class="ri-hotel-line font-weight-normal me-1" aria-hidden="true"></i>
                <span>Employeur</span>
                <span class="badge badge-sm rounded-pill ms-2">1</span>
            </a>
            """,
            html=True,
        )

        self.assertContains(response, capfirst(job.display_name), html=True)

        job_url = f"{job.get_absolute_url()}?back_url={urlencode_filter(response.wsgi_request.get_full_path())}"
        self.assertContains(response, job_url)

        company_url = f"{company.get_card_url()}?back_url={urlencode_filter(response.wsgi_request.get_full_path())}"
        self.assertContains(response, company_url)

    def test_district(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )
        filters_param = {"city": city_slug, "city_name": "Paris (75)", "distance": 25}

        company = CompanyFactory(department="75", coords=paris_city.coords, post_code="75001")
        job = JobDescriptionFactory(company=company)

        # Filter on city
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select the city
            + 1  # fetch initial job descriptions to add to the form fields
            + 2  # count the number of results for companies & job descriptions
            + 1  # prefetch job applications for the is_popular attribute
            + 1  # refetch the city for widget rendering
            + 1  # select the job descriptions for the page
        ):
            response = self.client.get(self.URL, {"city": city_slug})

        self.assertContains(response, "Emplois inclusifs à 25 km du centre de Paris (75)")
        self.assertContains(
            response,
            f"""
            <a class="nav-link active"
                data-matomo-event="true" data-matomo-category="candidature" data-matomo-action="clic"
                data-matomo-option="clic-onglet-fichesdeposte"
                href="{self.URL}?{escape(urlencode(filters_param))}">
                <i class="ri-briefcase-4-line font-weight-normal me-1" aria-hidden="true"></i>
                <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
                <span class="badge badge-sm rounded-pill ms-2">1</span>
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a class="nav-link"
                data-matomo-event="true" data-matomo-category="candidature"
                data-matomo-action="clic" data-matomo-option="clic-onglet-employeur"
                href="{self.URL_EMPLOYERS}?{escape(urlencode(filters_param))}">
                <i class="ri-hotel-line font-weight-normal me-1" aria-hidden="true"></i>
                <span>Employeur</span>
                <span class="badge badge-sm rounded-pill ms-2">1</span>
            </a>
            """,
            html=True,
        )

        # We can't support the city districts for now.
        self.assertNotContains(response, DISTRICTS)

        self.assertContains(response, capfirst(job.display_name), html=True)

    def test_kind(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        CompanyFactory(department="44", coords=city.coords, post_code="44117", kind=CompanyKind.AI)

        response = self.client.get(
            self.URL,
            {
                "city": city.slug,
                "city_name": city.name + " (44)",
                "distance": 25,
                "kinds": [CompanyKind.AI, CompanyKind.ETTI],
            },
        )
        self.assertContains(
            response,
            f"""
            <a class="nav-link"
                data-matomo-event="true" data-matomo-category="candidature"
                data-matomo-action="clic" data-matomo-option="clic-onglet-employeur"
                href="{self.URL_EMPLOYERS}?{escape(urlencode(response.wsgi_request.GET, doseq=True))}">
                <i class="ri-hotel-line font-weight-normal me-1" aria-hidden="true"></i>
                <span>Employeur</span>
                <span class="badge badge-sm rounded-pill ms-2">1</span>
            </a>
            """,
            html=True,
            count=1,
        )
        response = self.client.get(self.URL, {"city": city.slug, "kinds": [CompanyKind.EI]})
        self.assertContains(response, "Aucun résultat")

    @pytest.mark.ignore_unknown_variable_template_error
    def test_distance(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        # 3 companies in two departments to test distance and department filtering
        vannes = create_city_vannes()
        COMPANY_VANNES = "Entreprise Vannes"
        CompanyFactory(
            name=COMPANY_VANNES,
            department="56",
            coords=vannes.coords,
            post_code="56760",
            kind=CompanyKind.AI,
            with_jobs=True,
        )

        guerande = create_city_guerande()
        COMPANY_GUERANDE = "Entreprise Guérande"
        CompanyFactory(
            name=COMPANY_GUERANDE,
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=CompanyKind.AI,
            with_jobs=True,
        )
        saint_andre = create_city_saint_andre()
        COMPANY_SAINT_ANDRE = "Entreprise Saint André des Eaux"
        CompanyFactory(
            name=COMPANY_SAINT_ANDRE,
            department="44",
            coords=saint_andre.coords,
            post_code="44117",
            kind=CompanyKind.AI,
            with_jobs=True,
        )

        # 100 km
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">3</span>',
            html=True,
        )
        self.assertContains(response, COMPANY_VANNES.capitalize())
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 15})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">2</span>',
            html=True,
        )
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(
            response,
            '<span>Employeurs</span><span class="badge badge-sm rounded-pill ms-2">2</span>',
            html=True,
        )
        self.assertContains(response, COMPANY_GUERANDE.capitalize())
        self.assertContains(response, COMPANY_SAINT_ANDRE.capitalize())
        self.assertContains(response, "56 - Morbihan")  # the other department is still visible in the filters

        # 100 km and 56
        response = self.client.get(self.URL, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(
            response,
            '<span>Employeur</span><span class="badge badge-sm rounded-pill ms-2">1</span>',
            html=True,
        )
        self.assertContains(response, COMPANY_VANNES.capitalize())

    def test_order_by(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        guerande = create_city_guerande()

        company = CompanyFactory(department="44", coords=guerande.coords, post_code="44350")
        appellations = Appellation.objects.all()
        # get a different appellation for every job description, since they share the same
        job1 = JobDescriptionFactory(company=company, appellation=appellations[0])
        job2 = JobDescriptionFactory(company=company, appellation=appellations[1])
        job3 = JobDescriptionFactory(company=company, appellation=appellations[2])

        response = self.client.get(self.URL, {"city": guerande.slug})
        jobs_results = response.context["results_page"]

        assert list(jobs_results) == [job3, job2, job1]

        # check updated_at sorting also works
        job2.save()
        response = self.client.get(self.URL, {"city": guerande.slug})
        jobs_results = response.context["results_page"]
        assert list(jobs_results) == [job2, job3, job1]

        job1.save()
        response = self.client.get(self.URL, {"city": guerande.slug})
        jobs_results = response.context["results_page"]
        assert list(jobs_results) == [job1, job2, job3]

    def test_is_popular(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117")
        job = JobDescriptionFactory(company=company)
        JobApplicationFactory.create_batch(19, to_company=company, selected_jobs=[job], state="new")
        response = self.client.get(self.URL, {"city": city.slug})
        popular_badge = """
            <span class="badge badge-sm rounded-pill bg-accent-03 text-primary">
                <i class="ri-group-line me-1" aria-hidden="true"></i>
                20+<span class="ms-1">candidatures</span>
            </span>
            """
        self.assertNotContains(response, popular_badge, html=True)

        JobApplicationFactory(to_company=company, selected_jobs=[job], state="new")
        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(response, popular_badge, html=True)

    def test_no_department(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        st_andre = create_city_saint_andre()
        company_without_dpt = CompanyFactory(
            department="", coords=st_andre.coords, post_code="44117", kind=CompanyKind.AI
        )
        company = CompanyFactory(department="44", coords=st_andre.coords, post_code="44117", kind=CompanyKind.AI)
        JobDescriptionFactory(company=company_without_dpt, location=None)
        JobDescriptionFactory(company=company)
        response = self.client.get(self.URL, {"city": st_andre.slug})
        assert response.status_code == 200

    def test_contract_type(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117")
        appellations = Appellation.objects.filter(code__in=["10357", "10386", "10479"])

        job1 = JobDescriptionFactory(
            company=company, appellation=appellations[0], contract_type=ContractType.APPRENTICESHIP
        )
        job2 = JobDescriptionFactory(
            company=company, appellation=appellations[1], contract_type=ContractType.BUSINESS_CREATION
        )

        # Start active to verify it appears in search results.
        other_company = CompanyFactory(department="45", coords=city.coords, post_code="44117", kind=CompanyKind.EI)
        job3 = JobDescriptionFactory(
            company=other_company,
            appellation=appellations[2],
            contract_type=ContractType.APPRENTICESHIP,
        )

        job1_name = capfirst(job1.display_name)
        job2_name = capfirst(job2.display_name)
        job3_name = capfirst(job3.display_name)

        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">3</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, job1_name, html=True)
        self.assertContains(response, job2_name, html=True)
        self.assertContains(response, job3_name, html=True)

        other_company.convention = None
        other_company.save(update_fields=["convention"])

        # no filter: returns everything.
        response = self.client.get(
            self.URL,
            {"city": city.slug},
        )
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, job1_name, html=True)
        self.assertContains(response, job2_name, html=True)
        self.assertNotContains(response, job3_name, html=True)

        # pass both contract types, should have the same result.
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": [ContractType.APPRENTICESHIP, ContractType.BUSINESS_CREATION]},
        )
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, job1_name, html=True)
        self.assertContains(response, job2_name, html=True)
        self.assertNotContains(response, job3_name, html=True)

        # filter it down.
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": [ContractType.APPRENTICESHIP]},
        )
        self.assertContains(
            response,
            """
            <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">1</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, job1_name, html=True)
        self.assertNotContains(response, job2_name, html=True)
        self.assertNotContains(response, job3_name, html=True)

        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": [ContractType.OTHER]},
        )
        self.assertContains(response, "Aucun résultat")
        self.assertNotContains(response, job1_name, html=True)
        self.assertNotContains(response, job2_name, html=True)
        self.assertNotContains(response, job3_name, html=True)

    @pytest.mark.ignore_template_errors
    def test_domains(self):
        create_test_romes_and_appellations(("N1101", "M1805"))
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117")
        romes = Rome.objects.all().order_by("code")
        job1 = JobDescriptionFactory(
            company=company,
            appellation=romes[0].appellations.first(),
            contract_type=ContractType.APPRENTICESHIP,
            custom_name="Eviteur de Flakyness",
        )
        job2 = JobDescriptionFactory(
            company=company,
            appellation=romes[1].appellations.first(),
            contract_type=ContractType.BUSINESS_CREATION,
            custom_name="Forceur de Nom de Métier",
        )

        # Start active to verify it appears in search results.
        other_company = CompanyFactory(department="45", coords=city.coords, post_code="44117", kind=CompanyKind.EI)
        job3 = JobDescriptionFactory(
            company=other_company, contract_type=ContractType.APPRENTICESHIP, custom_name="Métier Inutilisé"
        )

        displayed_job_name_1 = capfirst(job1.display_name)
        displayed_job_name_2 = capfirst(job2.display_name)
        displayed_job_name_3 = capfirst(job3.display_name)

        response = self.client.get(self.URL, {"city": city.slug})
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">3</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertContains(response, displayed_job_name_2, html=True)
        self.assertContains(response, displayed_job_name_3, html=True)

        other_company.convention = None
        other_company.save(update_fields=["convention"])

        # no filter: returns everything.
        response = self.client.get(
            self.URL,
            {"city": city.slug},
        )
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        # pass both domains
        response = self.client.get(self.URL, {"city": city.slug, "domains": ["N", "M"]})
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        # filter it down.
        response = self.client.get(self.URL, {"city": city.slug, "domains": ["M"]})
        self.assertContains(
            response,
            """
            <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">1</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertNotContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        response = self.client.get(
            self.URL,
            {"city": city.slug, "domains": ["WAT"]},
        )
        self.assertContains(response, "Aucun résultat")
        self.assertNotContains(response, displayed_job_name_1, html=True)
        self.assertNotContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

    def test_pec_display(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        company = CompanyFactory(department="44", coords=city.coords, post_code="44117")
        appellations = Appellation.objects.all()
        job1 = JobDescriptionFactory(
            company=company, appellation=appellations[0], contract_type=ContractType.APPRENTICESHIP
        )
        pe_company = Company.unfiltered_objects.get(siret=POLE_EMPLOI_SIRET)
        job_pec = JobDescriptionFactory(
            company=pe_company,
            location=city,
            source_kind=JobSource.PE_API,
            source_id="fuuuuuuuu",
            source_url="https://external.pec.link/fuuuu",
            appellation=appellations[2],
            contract_type=ContractType.FIXED_TERM,
            other_contract_type="Super catégorie de genre de job",
            market_context_description="",
        )

        displayed_job_name_1 = capfirst(job1.display_name)
        displayed_job_pec = capfirst(job_pec.display_name)

        # no filter: returns everything.
        response = self.client.get(
            self.URL,
            {"city": city.slug},
        )

        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        assert list(response.context["results_page"]) == [job1, job_pec]
        self.assertContains(response, displayed_job_name_1)
        self.assertContains(response, displayed_job_pec)

        self.assertContains(response, "Contrat PEC - Parcours Emploi Compétences")
        self.assertContains(response, static("img/logo-france-travail.svg"))
        self.assertContains(
            response,
            '<span>Offre proposée et gérée par <span class="visually-hidden">France Travail</span></span>',
            html=True,
        )
        self.assertContains(response, "https://external.pec.link/fuuuu")

        self.assertContains(response, "Entreprise anonyme")
        self.assertContains(response, "Super catégorie de genre de job")
        RESERVED_PEC = "Réservé au public éligible au contrat PEC"
        self.assertNotContains(response, RESERVED_PEC)

        job_pec.contract_nature = ContractNature.PEC_OFFER
        job_pec.save(update_fields=["contract_nature"])
        response = self.client.get(
            self.URL,
            {"city": city.slug},
        )
        self.assertContains(response, RESERVED_PEC)

        # filter with "PEC offer" contract type: only returns the PEC offers
        # (whatever the actual contract_type of those)
        # no filter: returns everything.
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": ["PEC_OFFER"]},
        )
        self.assertContains(
            response,
            """
            <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">1</span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, displayed_job_name_1)
        self.assertContains(response, displayed_job_pec)

        # filter with PEC offer, apprenticeship: returns both
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": ["PEC_OFFER", "APPRENTICESHIP"]},
        )
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1)
        self.assertContains(response, displayed_job_pec)

        # filter with only apprenticeship: PEC offer not displayed (it's fixed term)
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": ["APPRENTICESHIP"]},
        )
        self.assertContains(
            response,
            """
            <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">1</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1)
        self.assertNotContains(response, displayed_job_pec)

        # filter with FIXED_TERM : PEC offer displayed because it's its underlying contract type
        response = self.client.get(
            self.URL,
            {"city": city.slug, "contract_types": ["FIXED_TERM"]},
        )
        self.assertContains(
            response,
            """
            <span>Poste <span class="d-none d-md-inline">ouvert au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">1</span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, displayed_job_name_1)
        self.assertContains(response, displayed_job_pec)

        # Show external company name
        job_pec.market_context_description = "MaPetiteEntreprise"
        job_pec.save(update_fields=["market_context_description"])
        response = self.client.get(
            self.URL,
            {"city": city.slug},
        )
        self.assertContains(
            response,
            """
            <span>Postes <span class="d-none d-md-inline">ouverts au recrutement</span></span>
            <span class="badge badge-sm rounded-pill ms-2">2</span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_pec)
        self.assertContains(response, "MaPetiteEntreprise")

    def test_htmx_reload(self):
        create_test_romes_and_appellations(("N1101",))
        guerande = create_city_guerande()
        company_guerande = CompanyFactory(
            name="Entreprise Guérande", department="44", coords=guerande.coords, post_code="44350"
        )
        JobDescriptionFactory(company=company_guerande)

        # Using SiaeSearchForm.DISTANCE_DEFAULT.
        response = self.client.get(self.URL, {"city": guerande.slug})
        simulated_page = parse_response_to_soup(response)

        def distance_radio(distance):
            [elt] = simulated_page.find_all("input", attrs={"name": "distance", "value": f"{distance}"})
            return elt

        distance_radio(100)["checked"] = "checked"
        del distance_radio(25)["checked"]
        response = self.client.get(
            self.URL,
            {"city": guerande.slug, "distance": 100},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{self.URL}']", response)
        response = self.client.get(self.URL, {"city": guerande.slug, "distance": 100})
        fresh_page = parse_response_to_soup(response)
        assertSoupEqual(simulated_page, fresh_page)
