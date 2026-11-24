from django.templatetags.static import static
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects


def test_documentation(client):
    response = client.get(reverse("v1:documentation"))
    assertContains(response, static("vendor/scalar/standalone.js"))
    assertContains(response, f'"url": "{reverse("v1:openapi_schema")}"')
    assertContains(response, '"agent": {"disabled": true}')
    assertContains(response, '"hideClientButton": true')


def test_legacy_redoc_url_redirects_to_documentation(client):
    response = client.get(reverse("v1:redoc"), {"lang": "fr"})
    assertRedirects(response, f"{reverse('v1:documentation')}?lang=fr", fetch_redirect_response=False, status_code=301)
