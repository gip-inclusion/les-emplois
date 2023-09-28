import pytest
from django.contrib.gis.geos import Point
from django.template.defaultfilters import capfirst
from django.test import override_settings
from django.urls import reverse

from itou.cities.models import City
from itou.jobs.models import Appellation, Rome
from itou.siaes.enums import POLE_EMPLOI_SIRET, ContractNature, ContractType, JobSource, SiaeKind
from itou.siaes.models import Siae
from tests.cities.factories import create_city_guerande, create_city_saint_andre, create_city_vannes
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.siaes.factories import SiaeFactory, SiaeJobDescriptionFactory, SiaeMembershipFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase


pytestmark = pytest.mark.ignore_template_errors


class SearchSiaeTest(TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("search:siaes_results")

    def test_not_existing(self):
        response = self.client.get(self.url, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")

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

        siae_1 = SiaeFactory(department="75", coords=paris_city.coords, post_code="75001")
        SiaeFactory(department="75", coords=paris_city.coords, post_code="75002")

        # Filter on city
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select the city
            + 1  # fetch initial SIAES (to extract the filters afterwards)
            + 2  # two counts for the tab headers
            + 1  # actual select of the SIAEs, with related objects and annotated distance
            + 1  # prefetch active job descriptions
        ):
            response = self.client.get(self.url, {"city": city_slug})

        self.assertContains(response, "Employeurs solidaires à 25 km du centre de Paris (75)")
        # look for the matomo_custom_title
        self.assertContains(response, "Recherche d&#x27;employeurs solidaires")
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>""",
            html=True,
        )
        self.assertContains(response, "Arrondissements de Paris")

        # Filter on district
        response = self.client.get(self.url, {"city": city_slug, "districts_75": ["75001"]})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )
        self.assertContains(response, siae_1.display_name)

        # Do not get arrondissements when searching the arrondissement directly
        response = self.client.get(self.url, {"city": "paris-10eme-75"})
        self.assertNotContains(response, "Arrondissements de Paris")

    def test_kind(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.AI]})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.EI]})
        self.assertContains(response, "Aucun résultat")

    def test_distance(self):
        # 3 SIAEs in two departments to test distance and department filtering
        vannes = create_city_vannes()
        SIAE_VANNES = "SIAE Vannes"
        SiaeFactory(name=SIAE_VANNES, department="56", coords=vannes.coords, post_code="56760", kind=SiaeKind.AI)

        guerande = create_city_guerande()
        SIAE_GUERANDE = "SIAE Guérande"
        SiaeFactory(name=SIAE_GUERANDE, department="44", coords=guerande.coords, post_code="44350", kind=SiaeKind.AI)
        saint_andre = create_city_saint_andre()
        SIAE_SAINT_ANDRE = "SIAE Saint André des Eaux"
        SiaeFactory(
            name=SIAE_SAINT_ANDRE, department="44", coords=saint_andre.coords, post_code="44117", kind=SiaeKind.AI
        )

        # 100 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">3</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_VANNES.capitalize())

    def test_order_by(self):
        """
        Check SIAE results sorting.
        Don't test sorting by active members to avoid creating too much data.
        """
        guerande = create_city_guerande()
        created_siaes = []

        # Several job descriptions but no job application.
        siae = SiaeFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        created_siaes.append(siae)

        # Many job descriptions and job applications.
        siae = SiaeFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_siae=siae)
        created_siaes.append(siae)

        # Many job descriptions and more job applications than the first one.
        siae = SiaeFactory(with_jobs=True, department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)
        created_siaes.append(siae)

        # No job description, no job application.
        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350")
        created_siaes.append(siae)

        # Does not want to receive any job application.
        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350", block_job_applications=True)
        created_siaes.append(siae)

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # find city
            + 1  # find siaes
            + 1  # count siaes
            + 1  # count job descriptions
            + 1  # get siaes infos
            + 1  # get job descriptions infos
        ):
            response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["results_page"]

        assert [siae.pk for siae in siaes_results] == [siae.pk for siae in created_siaes]

    def test_opcs_displays_card_differently(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.OPCS)

        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )
        self.assertContains(response, "Offres clauses sociales")

    def test_is_popular(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117", with_membership=True)
        job = SiaeJobDescriptionFactory(siae=siae)
        JobApplicationFactory.create_batch(20, to_siae=siae, selected_jobs=[job], state="new")
        response = self.client.get(self.url, {"city": city.slug})
        self.assertNotContains(response, """20+<span class="ml-1">candidatures</span>""", html=True)

        JobApplicationFactory(to_siae=siae, selected_jobs=[job], state="new")
        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(
            response,
            """
            <span class="badge badge-sm badge-pill badge-pilotage text-primary">
                <i class="ri-group-line mr-1"></i>
                20+<span class="ml-1">candidatures</span>
            </span>
            """,
            html=True,
        )

    def test_has_no_active_members(self):
        hiring_str = "recrutements en cours"
        no_hiring_str = (
            "Cet employeur n'est actuellement pas inscrit sur le site des emplois de l’inclusion, "
            "vous ne pouvez pas déposer de candidature en ligne"
        )
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117", with_jobs=True)
        response = self.client.get(self.url, {"city": city.slug})
        self.assertNotContains(response, hiring_str)
        self.assertContains(response, no_hiring_str)

        SiaeMembershipFactory(siae=siae)
        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(response, hiring_str)
        self.assertNotContains(response, no_hiring_str)


class SearchPrescriberTest(TestCase):
    def test_home(self):
        url = reverse("search:prescribers_home")
        response = self.client.get(url)
        self.assertContains(response, "Rechercher des prescripteurs habilités")

    def test_results(self):
        url = reverse("search:prescribers_results")

        vannes = create_city_vannes()
        guerande = create_city_guerande()
        PrescriberOrganizationFactory(authorized=True, coords=guerande.coords)
        PrescriberOrganizationFactory(authorized=True, coords=vannes.coords)

        response = self.client.get(url, {"city": guerande.slug, "distance": 100})
        self.assertContains(response, "2 résultats", html=True)

        response = self.client.get(url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "1 résultat", html=True)


class JobDescriptionSearchViewTest(TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("search:job_descriptions_results")

    def test_not_existing(self):
        response = self.client.get(self.url, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")

    def test_district(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        siae = SiaeFactory(department="75", coords=paris_city.coords, post_code="75001")
        job = SiaeJobDescriptionFactory(siae=siae)

        # Filter on city
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # select the city
            + 1  # fetch initial job descriptions to add to the form fields
            + 2  # count the number of results for siaes & job descriptions
            + 1  # select the job descriptions for the page
        ):
            response = self.client.get(self.url, {"city": city_slug})

        self.assertContains(response, "Employeurs solidaires à 25 km du centre de Paris (75)")
        self.assertContains(
            response,
            """
            <span class="d-none d-lg-inline">
                Poste ouvert au recrutement
                <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )

        # We can't support the city districts for now.
        self.assertNotContains(response, "Arrondissements de Paris")

        self.assertContains(response, capfirst(job.display_name), html=True)

    def test_kind(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.AI, SiaeKind.ETTI]})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.EI]})
        self.assertContains(response, "Aucun résultat")

    def test_distance(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        # 3 SIAEs in two departments to test distance and department filtering
        vannes = create_city_vannes()
        SIAE_VANNES = "SIAE Vannes"
        SiaeFactory(
            name=SIAE_VANNES,
            department="56",
            coords=vannes.coords,
            post_code="56760",
            kind=SiaeKind.AI,
            with_jobs=True,
        )

        guerande = create_city_guerande()
        SIAE_GUERANDE = "SIAE Guérande"
        SiaeFactory(
            name=SIAE_GUERANDE,
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=SiaeKind.AI,
            with_jobs=True,
        )
        saint_andre = create_city_saint_andre()
        SIAE_SAINT_ANDRE = "SIAE Saint André des Eaux"
        SiaeFactory(
            name=SIAE_SAINT_ANDRE,
            department="44",
            coords=saint_andre.coords,
            post_code="44117",
            kind=SiaeKind.AI,
            with_jobs=True,
        )

        # 100 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">3</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(
            response,
            """Employeurs <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())
        self.assertContains(response, "56 - Morbihan")  # the other department is still visible in the filters

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(
            response,
            """Employeur <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>""",
            html=True,
        )
        self.assertContains(response, SIAE_VANNES.capitalize())

    def test_order_by(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        guerande = create_city_guerande()

        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350")
        appellations = Appellation.objects.all()
        # get a different appellation for every job description, since they share the same SIAE
        job1 = SiaeJobDescriptionFactory(siae=siae, appellation=appellations[0])
        job2 = SiaeJobDescriptionFactory(siae=siae, appellation=appellations[1])
        job3 = SiaeJobDescriptionFactory(siae=siae, appellation=appellations[2])

        response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["results_page"]

        assert list(siaes_results) == [job3, job2, job1]

        # check updated_at sorting also works
        job2.save()
        response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["results_page"]
        assert list(siaes_results) == [job2, job3, job1]

        job1.save()
        response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["results_page"]
        assert list(siaes_results) == [job1, job2, job3]

    def test_is_popular(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117")
        job = SiaeJobDescriptionFactory(siae=siae)
        JobApplicationFactory.create_batch(20, to_siae=siae, selected_jobs=[job], state="new")
        response = self.client.get(self.url, {"city": city.slug})
        self.assertNotContains(response, """20+<span class="ml-1">candidatures</span>""", html=True)

        JobApplicationFactory(to_siae=siae, selected_jobs=[job], state="new")
        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(
            response,
            """
            <span class="badge badge-sm badge-pill badge-accent-03 text-primary">
                <i class="ri-group-line"></i>
                20+ candidatures
            </span>
            """,
            html=True,
        )

    def test_no_department(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        st_andre = create_city_saint_andre()
        siae_without_dpt = SiaeFactory(department="", coords=st_andre.coords, post_code="44117", kind=SiaeKind.AI)
        siae = SiaeFactory(department="44", coords=st_andre.coords, post_code="44117", kind=SiaeKind.AI)
        SiaeJobDescriptionFactory(siae=siae_without_dpt, location=None)
        SiaeJobDescriptionFactory(siae=siae)
        response = self.client.get(self.url, {"city": st_andre.slug})
        assert response.status_code == 200

    def test_contract_type(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117")
        appellations = Appellation.objects.filter(code__in=["10357", "10386", "10479"])

        job1 = SiaeJobDescriptionFactory(
            siae=siae, appellation=appellations[0], contract_type=ContractType.APPRENTICESHIP
        )
        job2 = SiaeJobDescriptionFactory(
            siae=siae, appellation=appellations[1], contract_type=ContractType.BUSINESS_CREATION
        )

        inactive_siae = SiaeFactory(
            department="45", coords=city.coords, post_code="44117", kind=SiaeKind.EI, convention=None
        )
        job3 = SiaeJobDescriptionFactory(
            siae=inactive_siae,
            appellation=appellations[2],
            contract_type=ContractType.APPRENTICESHIP,
        )

        # no filter: returns everything.
        response = self.client.get(
            self.url,
            {"city": city.slug},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job1.display_name), html=True)
        self.assertContains(response, capfirst(job2.display_name), html=True)
        self.assertNotContains(response, capfirst(job3.display_name), html=True)

        # pass both contract types, should have the same result.
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": [ContractType.APPRENTICESHIP, ContractType.BUSINESS_CREATION]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job1.display_name), html=True)
        self.assertContains(response, capfirst(job2.display_name), html=True)
        self.assertNotContains(response, capfirst(job3.display_name), html=True)

        # filter it down.
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": [ContractType.APPRENTICESHIP]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Poste <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job1.display_name), html=True)
        self.assertNotContains(response, capfirst(job2.display_name), html=True)
        self.assertNotContains(response, capfirst(job3.display_name), html=True)

        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": [ContractType.OTHER]},
        )
        self.assertContains(response, "Aucun résultat")
        self.assertNotContains(response, capfirst(job1.display_name), html=True)
        self.assertNotContains(response, capfirst(job2.display_name), html=True)
        self.assertNotContains(response, capfirst(job3.display_name), html=True)

    def test_domains(self):
        create_test_romes_and_appellations(("N1101", "M1805"))
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117")
        romes = Rome.objects.all().order_by("code")
        job1 = SiaeJobDescriptionFactory(
            siae=siae,
            appellation=romes[0].appellations.first(),
            contract_type=ContractType.APPRENTICESHIP,
            custom_name="Eviteur de Flakyness",
        )
        job2 = SiaeJobDescriptionFactory(
            siae=siae,
            appellation=romes[1].appellations.first(),
            contract_type=ContractType.BUSINESS_CREATION,
            custom_name="Forceur de Nom de Métier",
        )

        inactive_siae = SiaeFactory(
            department="45", coords=city.coords, post_code="44117", kind=SiaeKind.EI, convention=None
        )
        job3 = SiaeJobDescriptionFactory(
            siae=inactive_siae, contract_type=ContractType.APPRENTICESHIP, custom_name="Métier Inutilisé"
        )

        # no filter: returns everything.
        response = self.client.get(
            self.url,
            {"city": city.slug},
        )

        displayed_job_name_1 = capfirst(job1.display_name)
        displayed_job_name_2 = capfirst(job2.display_name)
        displayed_job_name_3 = capfirst(job3.display_name)

        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        # pass both domains
        response = self.client.get(self.url, {"city": city.slug, "domains": ["N", "M"]})
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        # filter it down.
        response = self.client.get(self.url, {"city": city.slug, "domains": ["M"]})
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Poste <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, displayed_job_name_1, html=True)
        self.assertNotContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

        response = self.client.get(
            self.url,
            {"city": city.slug, "domains": ["WAT"]},
        )
        self.assertContains(response, "Aucun résultat")
        self.assertNotContains(response, displayed_job_name_1, html=True)
        self.assertNotContains(response, displayed_job_name_2, html=True)
        self.assertNotContains(response, displayed_job_name_3, html=True)

    def test_pec_display(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        city = create_city_saint_andre()
        siae = SiaeFactory(department="44", coords=city.coords, post_code="44117")
        appellations = Appellation.objects.all()
        job1 = SiaeJobDescriptionFactory(
            siae=siae, appellation=appellations[0], contract_type=ContractType.APPRENTICESHIP
        )
        pe_siae = Siae.unfiltered_objects.get(siret=POLE_EMPLOI_SIRET)
        job_pec = SiaeJobDescriptionFactory(
            siae=pe_siae,
            location=city,
            source_kind=JobSource.PE_API,
            source_id="fuuuuuuuu",
            source_url="https://external.pec.link/fuuuu",
            appellation=appellations[2],
            contract_type=ContractType.FIXED_TERM,
            other_contract_type="Super catégorie de genre de job",
            market_context_description="",
        )

        # no filter: returns everything.
        response = self.client.get(
            self.url,
            {"city": city.slug},
        )

        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        assert list(response.context["results_page"]) == [job1, job_pec]
        self.assertContains(response, capfirst(job1.display_name))
        self.assertContains(response, capfirst(job_pec.display_name))

        self.assertContains(response, "Contrat PEC - Parcours Emploi Compétences")
        self.assertContains(response, "logo-pole-emploi.svg")
        self.assertContains(response, "Offre proposée et gérée par pole-emploi.fr")
        self.assertContains(response, "https://external.pec.link/fuuuu")

        self.assertContains(response, "Entreprise anonyme")
        self.assertContains(response, "Super catégorie de genre de job")
        self.assertNotContains(response, "Réservé au public éligible au contrat PEC")

        job_pec.contract_nature = ContractNature.PEC_OFFER
        job_pec.save(update_fields=["contract_nature"])
        response = self.client.get(
            self.url,
            {"city": city.slug},
        )
        self.assertContains(response, "Réservé au public éligible au contrat PEC")

        # filter with "PEC offer" contract type: only returns the PEC offers
        # (whatever the actual contract_type of those)
        # no filter: returns everything.
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": ["PEC_OFFER"]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Poste <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, capfirst(job1.display_name))
        self.assertContains(response, capfirst(job_pec.display_name))

        # filter with PEC offer, apprenticeship: returns both
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": ["PEC_OFFER", "APPRENTICESHIP"]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job1.display_name))
        self.assertContains(response, capfirst(job_pec.display_name))

        # filter with only apprenticeship: PEC offer not displayed (it's fixed term)
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": ["APPRENTICESHIP"]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Poste <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job1.display_name))
        self.assertNotContains(response, capfirst(job_pec.display_name))

        # filter with FIXED_TERM : PEC offer displayed because it's its underlying contract type
        response = self.client.get(
            self.url,
            {"city": city.slug, "contract_types": ["FIXED_TERM"]},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Poste <span class="badge badge-sm badge-pill badge-info-lighter text-info">1</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, capfirst(job1.display_name))
        self.assertContains(response, capfirst(job_pec.display_name))

        # Show external company name
        job_pec.market_context_description = "MaPetiteEntreprise"
        job_pec.save(update_fields=["market_context_description"])
        response = self.client.get(
            self.url,
            {"city": city.slug},
        )
        self.assertContains(
            response,
            """
            <span class="d-inline d-lg-none">
                Postes <span class="badge badge-sm badge-pill badge-info-lighter text-info">2</span>
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, capfirst(job_pec.display_name))
        self.assertContains(response, "MaPetiteEntreprise")
