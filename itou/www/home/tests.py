from django.urls import reverse

from itou.utils.test import TestCase


class SearchSiaeTest(TestCase):
    def test_home_search(self):
        url = reverse("home:hp")
        response = self.client.get(url)
        self.assertContains(response, "Prenez contact avec un employeur solidaire")
