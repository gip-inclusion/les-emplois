from django.urls import reverse

from tests.utils.test import TestCase


class SearchSiaeTest(TestCase):
    def test_home_search(self):
        url = reverse("home:hp")
        response = self.client.get(url)
        self.assertContains(response, "Rechercher un emploi inclusif")
