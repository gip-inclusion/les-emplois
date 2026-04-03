import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.dora.models import ReferenceDatumKind
from tests.dora.factories import ReferenceDatumFactory, ServiceFactory
from tests.users.factories import PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


def detail_url(service):
    return reverse("services:detail", kwargs={"uid": service.uid})


@pytest.fixture
def user(db):
    return PrescriberFactory()


@pytest.fixture
def service(db):
    return ServiceFactory(
        uid="test-service-uid",
        name="Mon service de test",
        updated_on="2025-01-15",
        structure__uid="test-structure-uid",
        structure__name="Ma structure de test",
        structure__updated_on="2025-01-15",
    )


def test_detail_requires_login(client, service):
    response = client.get(detail_url(service))
    assert response.status_code == 302
    assert "/accounts/login" in response["Location"]


def test_detail_basic(client, user, service, snapshot):
    client.force_login(user)
    response = client.get(detail_url(service))
    assert response.status_code == 200
    assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot


def test_detail_with_all_optional_fields(client, user, snapshot):
    source = ReferenceDatumFactory(kind=ReferenceDatumKind.SOURCE, value="dora", label="Dora")
    fee = ReferenceDatumFactory(kind=ReferenceDatumKind.FEE, value="gratuit", label="Gratuit")
    public = ReferenceDatumFactory(kind=ReferenceDatumKind.PUBLIC, value="adultes", label="Adultes")
    reception = ReferenceDatumFactory(kind=ReferenceDatumKind.RECEPTION, value="en-presentiel", label="En présentiel")
    thematic = ReferenceDatumFactory(
        kind=ReferenceDatumKind.THEMATIC, value="logement", label="Logement - Hébergement"
    )
    mobilization = ReferenceDatumFactory(
        kind=ReferenceDatumKind.MOBILIZATION, value="telephonique", label="Par téléphone"
    )

    service = ServiceFactory(
        uid="test-service-full-uid",
        name="Service complet",
        updated_on="2025-06-01",
        description="## Description complète\n\nAvec du **markdown**.",
        description_short="Résumé court du service.",
        source=source,
        source_link="https://dora.inclusion.gouv.fr/services/test",
        fee=fee,
        fee_details="Sous conditions de ressources.",
        publics_details="Toute personne majeure.",
        access_conditions="Être orienté par un prescripteur.",
        mobilizations_details="Contacter le service par téléphone.",
        contact_email="contact@service.fr",
        contact_phone="01 23 45 67 89",
        is_orientable_with_form=True,
        average_orientation_response_delay_days=3,
        opening_hours="Mo-Fr 09:00-17:00; PH off",
        address_line_1="12 rue de la Paix",
        address_line_2="Bâtiment B",
        post_code="75001",
        city="Paris",
        structure__uid="test-structure-full-uid",
        structure__name="Structure complète",
        structure__updated_on="2025-06-01",
    )
    service.publics.add(public)
    service.receptions.add(reception)
    service.thematics.add(thematic)
    service.mobilizations.add(mobilization)

    client.force_login(user)
    response = client.get(detail_url(service))
    assert response.status_code == 200
    assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot


def test_detail_orientable(client, user, snapshot):
    service = ServiceFactory(
        uid="test-orientable-uid",
        name="Service orientable",
        updated_on="2025-01-15",
        is_orientable_with_form=True,
        structure__uid="test-structure-orientable-uid",
        structure__updated_on="2025-01-15",
    )
    client.force_login(user)
    response = client.get(detail_url(service))
    assertContains(response, "Orienter le bénéficiaire")
    assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot


def test_detail_not_orientable(client, user, snapshot):
    service = ServiceFactory(
        uid="test-not-orientable-uid",
        name="Service non orientable",
        updated_on="2025-01-15",
        is_orientable_with_form=False,
        structure__uid="test-structure-not-orientable-uid",
        structure__updated_on="2025-01-15",
    )
    client.force_login(user)
    response = client.get(detail_url(service))
    assertNotContains(response, "Orienter le bénéficiaire")
    assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot


def test_detail_with_source_link(client, user):
    service_with_link = ServiceFactory(
        uid="test-with-link-uid",
        source_link="https://dora.inclusion.gouv.fr/services/test",
        updated_on="2025-01-15",
        structure__uid="test-structure-with-link-uid",
        structure__updated_on="2025-01-15",
    )
    client.force_login(user)
    response = client.get(detail_url(service_with_link))
    assertContains(response, '<link rel="canonical" href="https://dora.inclusion.gouv.fr/services/test">')


def test_detail_without_source_link(client, user):
    service_no_link = ServiceFactory(
        uid="test-no-link-uid",
        source_link="",
        updated_on="2025-01-15",
        structure__uid="test-structure-no-link-uid",
        structure__updated_on="2025-01-15",
    )
    client.force_login(user)
    response = client.get(detail_url(service_no_link))
    assertNotContains(response, 'rel="canonical"')
