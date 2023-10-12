from django.urls import reverse

from tests.utils.test import TestCase


class ReleaseTest(TestCase):
    def test_list(self):
        url = reverse("releases:list")
        response = self.client.get(url)
        self.assertContains(response, "Journal des modifications")
