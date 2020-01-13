from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class StatsViewTest(TestCase):
    def test_stats(self):

        url = reverse("stats:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for department in settings.ITOU_TEST_DEPARTMENTS:
            url = reverse("stats:index")
            response = self.client.post(url, data={"department": department})
            self.assertEqual(response.status_code, 200)
