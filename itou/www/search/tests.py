from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from itou.cities.models import City
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae


class SearchSiaeTest(TestCase):
    def setUp(self):
        self.url = reverse("search:siaes_results")

    def test_search_not_existing(self):
        response = self.client.get(self.url, {"city": "foo-44"})
        self.assertContains(response, "Aucun résultat.")

    def test_search_paris(self):
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris (75)", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
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

    def test_search_kind(self):
        city_slug = "saint-andre-des-eaux-44"
        city = City.objects.create(
            name="Saint-André-des-Eaux (75)",
            slug=city_slug,
            department="44",
            post_codes=["44117"],
            coords=Point(5, 23),
        )
        SiaeFactory(department="44", coords=city.coords, post_code="44117", kind=Siae.KIND_AI)

        response = self.client.get(self.url, {"city": city_slug, "kinds": [Siae.KIND_AI]})
        self.assertContains(response, "<b>1</b> résultat")

        response = self.client.get(self.url, {"city": city_slug, "kinds": [Siae.KIND_EI]})
        self.assertContains(response, "Aucun résultat")
