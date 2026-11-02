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
