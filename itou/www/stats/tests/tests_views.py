from django.test import TestCase, override_settings
from django.urls import reverse


class StatsViewTest(TestCase):
    def test_stats_public(self):
        url = reverse("stats:stats_public")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_stats_pilotage_unauthorized_dashboard_id(self):
        url = reverse("stats:stats_pilotage", kwargs={"dashboard_id": 123})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    @override_settings(PILOTAGE_DASHBOARDS_WHITELIST=[123])
    def test_stats_pilotage_authorized_dashboard_id(self):
        url = reverse("stats:stats_pilotage", kwargs={"dashboard_id": 123})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
