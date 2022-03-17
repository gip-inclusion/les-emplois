from django.test import TestCase
from django.urls import reverse


class SearchSiaeTest(TestCase):
    def test_home_search(self):
        url = reverse("home:hp")
        response = self.client.get(url)
        self.assertContains(response, "Pour l’inclusion par l’emploi")
