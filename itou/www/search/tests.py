from django.contrib.gis.geos import Point
from django.template.defaultfilters import capfirst
from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_city_guerande, create_city_saint_andre, create_city_vannes
from itou.cities.models import City
from itou.job_applications.factories import JobApplicationFactory
from itou.jobs.factories import create_test_romes_and_appellations
from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory, SiaeJobDescriptionFactory
from itou.www.testing import NUM_CSRF_SESSION_REQUESTS


class SearchSiaeTest(TestCase):
    def setUp(self):
        self.url = reverse("search:siaes_results")

    def test_not_existing(self):
        response = self.client.get(self.url, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")

    def test_district(self):
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        siae_1 = SiaeFactory(department="75", coords=paris_city.coords, post_code="75001")
        SiaeFactory(department="75", coords=paris_city.coords, post_code="75002")

        # Filter on city
        with self.assertNumQueries(
            1  # select the city
            + 1  # fetch initial SIAES (to extract the filters afterwards)
            + 2  # two counts for the tab headers
            + 1  # actual select of the SIAEs, with related objects and annotated distance
            + 1  # prefetch active job descriptions
            + NUM_CSRF_SESSION_REQUESTS
        ):
            response = self.client.get(self.url, {"city": city_slug})

        self.assertContains(response, "Employeurs solidaires à 25 km du centre de Paris (75)")
        self.assertContains(response, "(2 résultats)")
        self.assertContains(response, "Arrondissements de Paris")

        # Filter on district
        response = self.client.get(self.url, {"city": city_slug, "districts_75": ["75001"]})
        self.assertContains(response, "(1 résultat)")
        self.assertContains(response, siae_1.display_name)

    def test_kind(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.AI]})
        self.assertContains(response, "(1 résultat)")

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
        self.assertContains(response, "3 résultats")
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "2 résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(response, "2 résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(response, "1 résultat")
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

        response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["results_page"]

        self.assertEqual(
            [siae.pk for siae in siaes_results],
            [siae.pk for siae in created_siaes],
        )

    def test_opcs_displays_card_differently(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.OPCS)

        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(response, "1 résultat")
        self.assertContains(response, "Offres clauses sociales")

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
            <span class="badge badge-sm badge-pill badge-pilotage text-primary">
                <i class="ri-group-line mr-1"></i>
                20+<span class="ml-1">candidatures</span>
            </span>
            """,
            html=True,
        )


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
        self.assertContains(response, "<b>2</b> résultats", html=True)

        response = self.client.get(url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "<b>1</b> résultat", html=True)


class SearchJobDescriptionTest(TestCase):
    def setUp(self):
        # FIXME(vperron): this should probably be done ONCE with the initialization of any test DB,
        # which would also fix the constant calling of this with every test that uses SiaeFactory,
        # which is a slow process since it's reading JSON, injecting in the database, etc etc.
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        self.url = reverse("search:job_descriptions_results")

    def test_not_existing(self):
        response = self.client.get(self.url, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat avec les filtres actuels.")

    def test_district(self):
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        siae = SiaeFactory(department="75", coords=paris_city.coords, post_code="75001")
        job = SiaeJobDescriptionFactory(siae=siae)

        # Filter on city
        with self.assertNumQueries(
            1  # select the city
            + 1  # fetch initial job descriptions to add to the form fields
            + 2  # count the number of results for siaes & job descriptions
            + 1  # select the job descriptions pager
            + 1  # prefetch active job descriptions
            + NUM_CSRF_SESSION_REQUESTS
        ):
            response = self.client.get(self.url, {"city": city_slug})

        self.assertContains(response, "Employeurs solidaires à 25 km du centre de Paris (75)")
        self.assertContains(response, "Postes ouverts au recrutement")
        self.assertContains(response, "1 résultat")

        # We can't support the city districts for now.
        self.assertNotContains(response, "Arrondissements de Paris")

        self.assertContains(response, capfirst(job.display_name), html=True)

    def test_kind(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.AI]})
        self.assertContains(response, "(1 résultat)")

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.EI]})
        self.assertContains(response, "Aucun résultat")

    def test_distance(self):
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
        self.assertContains(response, "3 résultats")
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "2 résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(response, "2 résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(response, "1 résultat")
        self.assertContains(response, SIAE_VANNES.capitalize())

    def test_order_by(self):
        guerande = create_city_guerande()

        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350")
        job1 = SiaeJobDescriptionFactory(siae=siae)
        job2 = SiaeJobDescriptionFactory(siae=siae)
        job3 = SiaeJobDescriptionFactory(siae=siae)

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
        assert list(siaes_results) == [job2, job1, job3]

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
            <p class="badge badge-sm badge-pill badge-pilotage text-primary mb-3">
                <i class="ri-group-line mr-1"></i>
                20+<span class="ml-1">candidatures</span>
            </p>
            """,
            html=True,
        )
