import pytest
from django.urls import reverse

from tests.users.factories import PrescriberFactory
from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors


class SearchSiaeTest(TestCase):
    def test_home_anonymous(self):
        url = reverse("home:hp")
        response = self.client.get(url)
        response = self.client.get(url, follow=True)
        self.assertRedirects(response, reverse("search:employers_home"))
        self.assertContains(response, "Rechercher un emploi inclusif")

    def test_home_logged_in(self):
        self.client.force_login(PrescriberFactory())
        url = reverse("home:hp")
        response = self.client.get(url, follow=True)
        self.assertContains(response, "Rechercher un emploi inclusif")
