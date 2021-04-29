from django.test import TestCase
from django.urls import reverse


class ReleaseTest(TestCase):
    def test_list(self):
        url = reverse("releases:list")
        response = self.client.get(url)
        self.assertContains(response, "Journal des modifications")
