from django.conf import settings
from django.urls import reverse
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateUsed

from itou.insertion.models import SOURCE_DORA_VALUE, GenericReferenceItemKind, GenericReferenceItemSource
from tests.insertion.factories import GenericReferenceItemFactory, StructureFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


def test_card_view_anonymous_renders_description_tab(client, snapshot):
    structure = StructureFactory(
        name="Structure test",
        description="Description de test",
        source=GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DATA_INCLUSION,
            kind=GenericReferenceItemKind.SOURCE,
            value=SOURCE_DORA_VALUE,
        ),
        source_link=f"{settings.DORA_WWW_BASE_URL}/structures/structure-test",
    )
    with assertSnapshotQueries(snapshot):
        response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

    assert response.context["structure"] == structure
    assertTemplateUsed(response, "insertion/structure_card.html")
    assertContains(response, "Structure test")
    assertContains(response, "Présentation de la structure")
    assertContains(response, "Description de test")
    assertContains(
        response,
        f'<link rel="canonical" href="{settings.DORA_WWW_BASE_URL}/structures/structure-test">',
        html=True,
    )


def test_card_view_non_dora_source_has_no_canonical(client):
    structure = StructureFactory(
        source=GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DATA_INCLUSION,
            kind=GenericReferenceItemKind.SOURCE,
            value="other",
        ),
        source_link="https://example.com/structures/structure-test",
    )
    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

    assertNotContains(response, 'rel="canonical"', html=True)


def test_card_view_not_found(client):
    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": "unknown-uid"}))

    assert response.status_code == 404


def test_card_view_contact_modal_contains_structure_coordinates(client, snapshot):
    structure = StructureFactory(
        email="contact@structure.test",
        phone="+33102030405",
        address_line_1="10 rue de la Paix",
        post_code="75002",
        city="Paris",
        website="https://structure.test",
    )
    response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

    modal = parse_response_to_soup(response, selector="#structure-contact-modal")
    assert pretty_indented(modal) == snapshot
