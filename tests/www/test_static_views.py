import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains


@pytest.mark.parametrize(
    "view_name,expected_title",
    [
        ("accessibility", "<h1>Déclaration d'accessibilité</h1>"),
        ("legal-notice", "<h1>Mentions légales</h1>"),
        ("legal-privacy", "<h1>Politique de confidentialité</h1>"),
        ("legal-terms", '<h1 id="conditions-générales-dutilisation">Conditions Générales d&#39;Utilisation</h1>'),
    ],
)
def test_navigation_not_authenticated(client, view_name, expected_title):
    response = client.get(reverse(view_name))
    assertContains(response, expected_title)
