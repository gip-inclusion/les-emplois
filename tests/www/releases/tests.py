from django.urls import reverse
from pytest_django.asserts import assertContains


class TestRelease:
    def test_list(self, client):
        url = reverse("releases:list")
        response = client.get(url)
        assertContains(response, "Journal des modifications")
