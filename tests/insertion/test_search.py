from itou.insertion.models import SearchLexeme, Service
from tests.insertion.factories import GenericReferenceItemFactory, ServiceFactory


def test_update_search_index():
    service = ServiceFactory(
        name="Garage solidaire",
        description="Réparation de véhicules",
        publics_details="Personnes sans emploi",
        structure__name="Agefiph",
        structure__description="Insertion des personnes handicapées",
        structure__reseaux_porteurs=[GenericReferenceItemFactory(kind="NETWORK", label="France Travail")],
        thematics=[
            GenericReferenceItemFactory(
                kind="THEMATIC",
                value="choisir-un-metier--decouvrir-un-metier-ou-un-secteur-dactivite",
                label="Découvrir un métier",
            )
        ],
        publics=[GenericReferenceItemFactory(kind="PUBLIC", label="Jeunes")],
    )

    Service.include_inactive.update_search_index()

    service.refresh_from_db()
    assert service.search_vector == (
        "'agefiph':11B 'decouvr':1A 'emploi':22C 'franc':9B 'garag':5A 'handicape':18B 'insert':15B 'jeun':19C "
        "'meti':3A 'person':17B,20C 'reconvers':4A 'repar':12B 'san':21C 'solidair':6A 'travail':10B 'vehicul':14B "
        "'zzdecouvertemetier':7A 'zzforummetiers':8A"
    )


def test_update_search_index_without_thematics_nor_publics():
    service = ServiceFactory(name="Garage solidaire", thematics=[])

    Service.include_inactive.update_search_index()

    service.refresh_from_db()
    assert "'garag':1A" in service.search_vector


def test_update_search_index_refreshes_lexicon():
    SearchLexeme.objects.create(word="obsolete", ndoc=1)
    ServiceFactory(
        name="Garage solidaire", description="", structure__name="Garage", structure__description="", thematics=[]
    )
    ServiceFactory(name="Garage", description="", structure__name="Mobilité", structure__description="", thematics=[])
    ServiceFactory(name="Inactif", is_active=False, thematics=[])

    Service.include_inactive.update_search_index()

    assert dict(SearchLexeme.objects.values_list("word", "ndoc")) == {
        "garag": 2,
        "mobilit": 1,
        "solidair": 1,
    }
