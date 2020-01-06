from django.test import TestCase
from django.urls import reverse


class StatsViewTest(TestCase):
    def test_stats(self):

        url = reverse("stats:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
