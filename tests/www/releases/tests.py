import pytest
from django.urls import reverse

from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors


class ReleaseTest(TestCase):
    def test_list(self):
        url = reverse("releases:list")
        response = self.client.get(url)
        self.assertContains(response, "Journal des modifications")
