import pytest

from itou.insertion.models import Service
from tests.insertion.factories import GenericReferenceItemFactory, ServiceFactory


def test_update_search_index():
    service = ServiceFactory(
        name="Garage solidaire",
        description="Réparation de véhicules",
        publics_details="Personnes sans emploi",
        structure__name="Agefiph",
        structure__description="Insertion des personnes handicapées",
        structure__reseaux_porteurs=[GenericReferenceItemFactory(kind="NETWORK", label="France Travail")],
        thematics=[GenericReferenceItemFactory(kind="THEMATIC", label="Découvrir un métier")],
        publics=[GenericReferenceItemFactory(kind="PUBLIC", label="Jeunes")],
    )

    Service.include_inactive.update_search_index()

    service.refresh_from_db()
    assert service.search_vector == (
        "'agefiph':8 'decouvr':1 'emploi':19 'franc':6 'garag':4 'handicape':15 'insert':12 'jeun':16 'meti':3 "
        "'person':14,17 'repar':9 'san':18 'solidair':5 'travail':7 'vehicul':11"
    )


def test_update_search_index_without_thematics_nor_publics():
    service = ServiceFactory(name="Garage solidaire", thematics=[])

    Service.include_inactive.update_search_index()

    service.refresh_from_db()
    assert "'garag':1" in service.search_vector


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Agefiph"),
        ("description", "Agefiph"),
        ("publics_details", "Agefiph"),
        ("structure__name", "L'Agefiph Hauts-de-France"),
        ("structure__description", "Agefiph"),
    ],
)
def test_keyword_search_by_field(field, value):
    service = ServiceFactory(**{field: value})
    ServiceFactory()
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("agefiph")) == [service]


@pytest.mark.parametrize(
    "relation,kind",
    [
        ("thematics", "THEMATIC"),
        ("publics", "PUBLIC"),
        ("structure__reseaux_porteurs", "NETWORK"),
    ],
)
def test_keyword_search_by_reference_item(relation, kind):
    service = ServiceFactory(**{relation: [GenericReferenceItemFactory(kind=kind, label="Agefiph")]})
    ServiceFactory()
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("agefiph")) == [service]


def test_keyword_search_ignores_receptions():
    ServiceFactory(receptions=[GenericReferenceItemFactory(kind="RECEPTION", label="Agefiph")])
    Service.include_inactive.update_search_index()

    assert not Service.objects.keyword_search("agefiph").exists()


def test_keyword_search_requires_every_word():
    ServiceFactory(name="Garage solidaire")
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search("garage solidaire").exists()
    assert not Service.objects.keyword_search("garage associatif").exists()


@pytest.mark.parametrize("name,q", [("Mobilité", "mobilite"), ("Mobilite", "mobilité")])
def test_keyword_search_ignores_accents(name, q):
    service = ServiceFactory(name=name)
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search(q)) == [service]


def test_keyword_search_hyphenated_word():
    service = ServiceFactory(name="Location de deux-roues", thematics=[])
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("deux-roues")) == [service]


@pytest.mark.parametrize("q", ["", "   ", "le", "de la"])
def test_keyword_search_without_any_word(q):
    ServiceFactory(name="Le garage de la ville")
    Service.include_inactive.update_search_index()

    assert not Service.objects.keyword_search(q).exists()
