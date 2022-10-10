from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_city_guerande, create_city_saint_andre, create_city_vannes
from itou.cities.models import City
from itou.job_applications.factories import JobApplicationFactory
from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory


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
        self.assertContains(response, "2 résultats sur 2")
        self.assertContains(response, "Arrondissements de Paris")

        # Filter on district
        response = self.client.get(self.url, {"city": city_slug, "districts_75": ["75001"]})
        self.assertContains(response, "1 résultat sur 1")
        self.assertContains(response, siae_1.display_name)

    def test_kind(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.AI)

        response = self.client.get(self.url, {"city": city.slug, "kinds": [SiaeKind.AI]})
        self.assertContains(response, "1 résultat sur 1")

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
        self.assertContains(response, "3 résultats sur 3")
        self.assertContains(response, SIAE_VANNES.capitalize())
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 15 km
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 15})
        self.assertContains(response, "2 résultats sur 2")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 44
        response = self.client.get(self.url, {"city": guerande.slug, "distance": 100, "departments": ["44"]})
        self.assertContains(response, "2 résultats sur 2")
        self.assertContains(response, SIAE_GUERANDE.capitalize())
        self.assertContains(response, SIAE_SAINT_ANDRE.capitalize())

        # 100 km and 56
        response = self.client.get(self.url, {"city": vannes.slug, "distance": 100, "departments": ["56"]})
        self.assertContains(response, "1 résultat sur 1")
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
        siaes_results = response.context["siaes_page"]

        self.assertEqual(
            [siae.pk for siae in siaes_results],
            [siae.pk for siae in created_siaes],
        )

    def test_opcs_displays_card_differently(self):
        city = create_city_saint_andre()
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=SiaeKind.OPCS)

        response = self.client.get(self.url, {"city": city.slug})
        self.assertContains(response, "1 résultat sur 1")
        self.assertContains(response, "Offres clauses sociales")


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
