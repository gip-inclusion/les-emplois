from django.test import TestCase
from django.urls import reverse

from itou.utils.address.departments import DEPARTMENTS


class StatsViewTest(TestCase):
    def test_stats(self):

        url = reverse("stats:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for department in DEPARTMENTS.keys():
            url = reverse("stats:index")
            response = self.client.post(url, data={"department": department})
            self.assertEqual(response.status_code, 200)
