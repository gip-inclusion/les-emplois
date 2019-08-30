from django.test import TestCase
from django.urls import reverse

from itou.siaes.factories import SiaeFactory


class CardViewTest(TestCase):
    def test_card(self):
        siae = SiaeFactory()
        url = reverse("siaes_views:card", kwargs={"siret": siae.siret})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response_content = str(response.content)
        self.assertIn(siae.display_name, response_content)
        self.assertIn(siae.phone, response_content)
        self.assertIn(siae.email, response_content)
