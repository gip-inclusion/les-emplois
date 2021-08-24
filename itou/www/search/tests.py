from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_city_guerande, create_city_saint_andre, create_city_vannes
from itou.cities.models import City
from itou.job_applications.factories import JobApplicationFactory
from itou.prescribers.factories import AuthorizedPrescriberOrganizationFactory
from itou.siaes.factories import SiaeFactory, SiaeWithJobsFactory
from itou.siaes.models import Siae


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
        response = self.client.get(self.url, {"city": city_slug})

        self.assertContains(response, "Employeurs solidaires à 25 km du centre de Paris (75)")
        self.assertContains(response, "<b>2</b> résultats")
        self.assertContains(response, "Arrondissements de Paris")

        # Filter on district
        response = self.client.get(self.url, {"city": city_slug, "districts_75": ["75001"]})
        self.assertContains(response, "<b>1</b> résultat")
        self.assertContains(response, siae_1.display_name)

    def test_kind(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=Siae.KIND_AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [Siae.KIND_AI]})
        self.assertContains(response, "<b>1</b> résultat")

        response = self.client.get(self.url, {"city": city.slug, "kinds": [Siae.KIND_EI]})
        self.assertContains(response, "Aucun résultat")

    def test_distance(self):
        # 3 SIAEs in two departments to test distance and department filtering
        vannes = create_city_vannes()
        SIAE_VANNES = "SIAE Vannes"
        SiaeFactory(name=SIAE_VANNES, department="56", coords=vannes.coords, post_code="56760", kind=Siae.KIND_AI)

        guerande = create_city_guerande()
        SIAE_GUERANDE = "SIAE Guérande"
        SiaeFactory(name=SIAE_GUERANDE, department="44", coords=guerande.coords, post_code="44350", kind=Siae.KIND_AI)
        saint_andre = create_city_saint_andre()
        SIAE_SAINT_ANDRE = "SIAE Saint André des Eaux"
        SiaeFactory(
            name=SIAE_SAINT_ANDRE, department="44", coords=saint_andre.coords, post_code="44117", kind=Siae.KIND_AI
        )

        # 100 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100})
        self.assertContains(response, "<b>3</b> résultats")
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "<b>2</b> résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(response, "<b>2</b> résultats")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(response, "<b>1</b> résultat")
        self.assertContains(response, SIAE_VANNES.capitalize())

    def test_order_by(self):
        """
        Check SIAE results sorting.
        Don't test sorting by active members to avoid creating too much data.
        """
        guerande = create_city_guerande()
        created_siaes = []

        # Several job descriptions but no job application.
        siae = SiaeWithJobsFactory(department="44", coords=guerande.coords, post_code="44350")
        created_siaes.append(siae)

        # Many job descriptions and job applications.
        siae = SiaeWithJobsFactory(department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_siae=siae)
        created_siaes.append(siae)

        # Many job descriptions and more job applications than the first one.
        siae = SiaeWithJobsFactory(department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_siae=siae)
        JobApplicationFactory(to_siae=siae)
        created_siaes.append(siae)

        # No job description and a job application
        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350")
        JobApplicationFactory(to_siae=siae)
        created_siaes.append(siae)

        # No job description, no job application.
        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350")
        created_siaes.append(siae)

        # Does not want to receive any job application.
        siae = SiaeFactory(department="44", coords=guerande.coords, post_code="44350", block_job_applications=True)
        created_siaes.append(siae)

        response = self.client.get(self.url, {"city": guerande.slug})
        siaes_results = response.context["siaes_page"]

        for i, siae in enumerate(siaes_results):
            self.assertEqual(siae.pk, created_siaes[i].pk)


class SearchPrescriberTest(TestCase):
    def test_home(self):
        url = reverse("search:prescribers_home")
        response = self.client.get(url)
        self.assertContains(response, "Rechercher des prescripteurs habilités")

    def test_results(self):
        url = reverse("search:prescribers_results")

        vannes = create_city_vannes()
        guerande = create_city_guerande()
        AuthorizedPrescriberOrganizationFactory(coords=guerande.coords)
        AuthorizedPrescriberOrganizationFactory(coords=vannes.coords)

        response = self.client.get(url, {"city": guerande.slug, "distance": 100})
        self.assertContains(response, "<b>2</b> résultats")

        response = self.client.get(url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "<b>1</b> résultat")
