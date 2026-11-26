import pytest
from django.templatetags.static import static
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.api import documentation as documentation_module
from itou.api.documentation import DOCUMENTATIONS, TAG_DESCRIPTIONS


def _operations(schema):
    return [operation for path in schema["paths"].values() for operation in path.values()]


@pytest.mark.parametrize("slug", DOCUMENTATIONS)
def test_documentation(client, slug):
    response = client.get(reverse("v1:documentation", kwargs={"slug": slug}))
    assertContains(response, static("vendor/scalar/standalone.js"))
    assertContains(response, f'"url": "{reverse("v1:documentation_schema", kwargs={"slug": slug})}"')
    assertContains(response, '"agent": {"disabled": true}')
    assertContains(response, '"hideClientButton": true')


def test_unknown_documentation(client):
    response = client.get(reverse("v1:documentation", kwargs={"slug": "unknown"}))
    assert response.status_code == 404
    response = client.get(reverse("v1:documentation_schema", kwargs={"slug": "unknown"}))
    assert response.status_code == 404


@pytest.mark.parametrize("documentation", DOCUMENTATIONS.values(), ids=DOCUMENTATIONS)
def test_documentation_schema(client, documentation):
    response = client.get(reverse("v1:documentation_schema", kwargs={"slug": documentation.slug}), {"format": "json"})
    schema = response.json()
    assert schema["info"]["title"].startswith(documentation.title)
    assert {tag for operation in _operations(schema) for tag in operation["tags"]} == set(documentation.tags)


def test_documentation_schema_only_has_its_tags(client, monkeypatch):
    monkeypatch.setattr(
        documentation_module,
        "TAG_DESCRIPTIONS",
        {
            "embauches-geiq": "Description des embauches GEIQ",
            "candidats": "Description des candidats",
            "siaes": "Description des SIAE",
        },
    )

    def get_schema(slug):
        return client.get(reverse("v1:documentation_schema", kwargs={"slug": slug}), {"format": "json"}).json()

    # In the order of `Documentation.tags`.
    assert get_schema("employeurs")["tags"] == [
        {"name": "candidats", "description": "Description des candidats"},
        {"name": "embauches-geiq", "description": "Description des embauches GEIQ"},
    ]
    assert get_schema("siae")["tags"] == [{"name": "siaes", "description": "Description des SIAE"}]
    assert "tags" not in get_schema("interne")


def test_every_tag_description_belongs_to_a_documentation():
    # Check that the items from TAG_DESCRIPTIONS all match a tag used in a documentation
    documentation_tags = {tag for documentation in DOCUMENTATIONS.values() for tag in documentation.tags}
    assert set(TAG_DESCRIPTIONS) <= documentation_tags


def test_every_tag_is_in_a_documentation(client):
    # Assert that we didn't forget a tag
    response = client.get(reverse("v1:openapi_schema"), {"format": "json"})
    tags = {tag for operation in _operations(response.json()) for tag in operation["tags"]}
    documentation_tags = {tag for documentation in DOCUMENTATIONS.values() for tag in documentation.tags}
    assert tags - {"oas3"} == documentation_tags


def test_legacy_documentation_urls_redirect_to_api_index(client):
    response = client.get(reverse("v1:redoc"))
    assertRedirects(response, reverse("api:index"), fetch_redirect_response=False, status_code=301)
