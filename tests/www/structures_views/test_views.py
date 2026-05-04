from types import SimpleNamespace

from django.http import Http404
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from tests.utils.testing import parse_response_to_soup


def _make_structure(uid="structure-uid", **kwargs):
    structure = SimpleNamespace(
        uid=uid,
        name="Structure test",
        description="Description de test",
    )
    for key, value in kwargs.items():
        setattr(structure, key, value)
    return structure


def test_card_view_anonymous_renders_description_tab(client, mocker):
    structure = _make_structure()
    mocker.patch("itou.www.insertion_views.views.get_object_or_404", return_value=structure)
    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

    assert response.status_code == 200
    assert response.context["structure"] == structure
    assert response.context["matomo_custom_title"] == "Fiche structure d’insertion"
    assertTemplateUsed(response, "insertion/structure_card.html")
    assert parse_response_to_soup(response, selector="#main h1").text.strip() == "Structure test"
    assert parse_response_to_soup(response, selector="#main article h3").text.strip() == "Présentation de la structure"
    assert "Description de test" in parse_response_to_soup(response, selector="#main article").text


def test_card_view_not_found(client, mocker):
    mocker.patch("itou.www.insertion_views.views.get_object_or_404", side_effect=Http404)

    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": "unknown-uid"}))

    assert response.status_code == 404


def test_card_view_contact_modal_contains_structure_coordinates(client, mocker):
    structure = _make_structure(
        email="contact@structure.test",
        phone="+33102030405",
        address_on_one_line="10 rue de la Paix, 75002 Paris",
        website="https://structure.test",
    )
    mocker.patch("itou.www.insertion_views.views.get_object_or_404", return_value=structure)

    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

    soup = parse_response_to_soup(response)
    assert soup.select_one('button[data-bs-target="#structure-contact-modal"]').text.strip() == (
        "Voir les coordonnées de la structure"
    )

    modal = soup.select_one("#structure-contact-modal")
    assert modal.select_one("#structure-contact-modal-label").text.strip() == "Coordonnées de contact"

    modal_body = modal.select_one(".modal-body")
    body_text = modal_body.get_text()
    for fragment in (
        "contact@structure.test",
        "01 02 03 04 05",
        "10 rue de la Paix, 75002 Paris",
        "https://structure.test",
    ):
        assert fragment in body_text

    for clipboard_value in ("contact@structure.test", "+33102030405"):
        button = modal.select_one(f'button[data-it-copy-to-clipboard="{clipboard_value}"]')
        assert button["data-it-clipboard-button"] == "copy"

    assert modal.select_one('a[href="https://structure.test"]')["href"] == "https://structure.test"
