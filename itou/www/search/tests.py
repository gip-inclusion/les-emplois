from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from itou.cities.models import City
from itou.prescribers.factories import AuthorizedPrescriberOrganizationFactory
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae


def create_city_saint_andre():
    return City.objects.create(
        name="Saint-André-des-Eaux",
        slug="saint-andre-des-eaux-44",
        department="44",
        coords=Point(-2.3140436, 47.3618584),
        post_codes=["44117"],
        code_insee="44117",
    )


def create_city_guerande():
    return City.objects.create(
        name="Guérande",
        slug="guerande-44",
        department="44",
        coords=Point(-2.4747713, 47.3358576),
        # Dummy
        post_codes=["44350"],
        code_insee="44350",
    )


def create_city_vannes():
    return City.objects.create(
        name="Vannes",
        slug="vannes-56",
        department="56",
        coords=Point(-2.8186843, 47.657641),
        # Dummy
        post_codes=["56000"],
        code_insee="56000",
    )


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


class SearchPrescriberTest(TestCase):
    def test_home(self):
        url = reverse("search:prescribers_home")
        response = self.client.get(url)
        self.assertContains(response, "Rechercher des prescripteurs")

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
