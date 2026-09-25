from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from tests.www.directory_views.helpers import get_target_person, setup_directory


def test_person_detail_preserves_back_url_and_hides_contact(client):
    _, target, target_organization, person = get_target_person(client)
    back_url = f"{reverse('directory:people_results')}?q=Alice"

    response = client.get(reverse("directory:person_detail", kwargs={"key": person.key}), {"back_url": back_url})

    assert response.status_code == 200
    assert response.context["back_url"] == back_url
    assertNotContains(response, target.email)
    assertNotContains(response, target.phone)
    assertNotContains(response, target_organization.email)
    assertNotContains(response, target_organization.phone)
    assertContains(response, "Afficher l'adresse e-mail")
    assertContains(response, "Afficher le téléphone de la structure")
    assertContains(response, "Annuaire Pro en accès bêta restreint")
    assertContains(response, target_organization.get_card_url())
    assertContains(response, "https://mission-locale.example")


def test_person_detail_displays_missing_phone(client):
    _, _, _, person = get_target_person(client, target_phone="")

    response = client.get(reverse("directory:person_detail", kwargs={"key": person.key}))

    assertContains(response, "<strong>Téléphone :</strong> Non renseigné", html=True)


def test_person_detail_unknown_key(client):
    setup_directory(client)

    response = client.get(reverse("directory:person_detail", kwargs={"key": "invalid"}))

    assert response.status_code == 404


def test_reveal_contact(client):
    _, target, target_organization, person = get_target_person(client)

    response = client.get(reverse("directory:reveal_contact", kwargs={"key": person.key, "field": "email"}))

    assertContains(response, target.email)
    assertContains(response, "data-it-copy-to-clipboard")

    response = client.get(
        reverse("directory:reveal_contact", kwargs={"key": person.key, "field": "phone"}),
        {"org": person.main_organization.key},
    )

    assertContains(response, target_organization.phone)
    assertContains(response, "Téléphone de la structure")


def test_reveal_contact_rejects_unknown_field(client):
    _, _, _, person = get_target_person(client)

    response = client.get(reverse("directory:reveal_contact", kwargs={"key": person.key, "field": "website"}))

    assert response.status_code == 404
