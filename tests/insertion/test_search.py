import pytest
from pytest_django.asserts import assertNumQueries

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
    service = ServiceFactory(
        **{
            "name": "Lorem",
            "description": "Lorem ipsum",
            "structure__name": "Lorem",
            "structure__description": "Lorem ipsum",
            field: value,
        }
    )
    ServiceFactory(
        name="Lorem", description="Lorem ipsum", structure__name="Lorem", structure__description="Lorem ipsum"
    )
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("agefiph")) == [service]


@pytest.mark.parametrize(
    "relation,kind,label,q,expected",
    [
        ("thematics", "THEMATIC", "Soutien aux aidants", "Soutien aux aidants", True),
        ("publics", "PUBLIC", "Jeunes", "jeunes", True),
        ("structure__reseaux_porteurs", "NETWORK", "France Travail", "France Travail", True),
        ("receptions", "RECEPTION", "En présentiel", "présentiel", False),
    ],
)
def test_keyword_search_by_reference_item(relation, kind, label, q, expected):
    ServiceFactory(
        name="Lorem",
        description="Lorem ipsum",
        structure__name="Lorem",
        structure__description="Lorem ipsum",
        **{relation: [GenericReferenceItemFactory(kind=kind, label=label)]},
    )
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search(q).exists() is expected


@pytest.mark.parametrize(
    "name,q",
    [
        ("mobilite", "mobilite"),
        ("mobilité", "mobilite"),
        ("mobilité", "mobilité"),
        ("mobilite", "mobilité"),
    ],
)
def test_keyword_search_accents(name, q):
    ServiceFactory(name=name)
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search(q).count() == 1


@pytest.mark.parametrize(
    "names,q,expected_count",
    [
        (["Lutte contre l'illettrisme"], "illetrisme", 1),
        (["Garage solidaire"], "garage solidiare", 1),
        (["Illettrisme", "Illetrisme"], "illetrisme", 2),
        (["Garage solidaire"], "garage tracteur", 0),
        (["Location de deux-roues"], "deux-roues", 1),
    ],
)
def test_keyword_search_typos(names, q, expected_count):
    for name in names:
        ServiceFactory(name=name, description="", structure__name="Lorem", structure__description="", thematics=[])
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search(q).count() == expected_count


@pytest.mark.parametrize("q", ["", "   ", "le", "de la"])
def test_keyword_search_without_lexeme(q):
    ServiceFactory(name="Le garage de la ville")
    Service.include_inactive.update_search_index()

    assert not Service.objects.keyword_search(q).exists()


@pytest.mark.parametrize(
    "q,expected",
    [
        ("reconversion", True),
        ("titre de séjour", True),
        ("Titre de Séjour", True),
        ("titre", False),
    ],
)
def test_keyword_search_thematic_aliases(q, expected):
    ServiceFactory(
        name="Lorem",
        description="Lorem ipsum",
        structure__name="Lorem",
        structure__description="Lorem ipsum",
        thematics=[
            GenericReferenceItemFactory(
                kind="THEMATIC",
                value="choisir-un-metier--decouvrir-un-metier-ou-un-secteur-dactivite",
                label="Découvrir un métier ou un secteur d'activité",
            ),
            GenericReferenceItemFactory(
                kind="THEMATIC",
                value="difficultes-administratives-ou-juridiques--accompagnement-pour-lacces-a-la-citoyennete",
                label="Accompagnement pour l'accès à la citoyenneté",
            ),
        ],
    )
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search(q).exists() is expected


@pytest.mark.parametrize(
    "best_field,other_field",
    [
        ("name", "structure__name"),
        ("structure__name", "publics_details"),
    ],
)
def test_keyword_search_weights(best_field, other_field):
    defaults = {
        "name": "Lorem",
        "description": "Lorem ipsum",
        "structure__name": "Lorem",
        "structure__description": "",
    }
    other = ServiceFactory(**{**defaults, other_field: "Agefiph"})
    best = ServiceFactory(**{**defaults, best_field: "Agefiph"})
    Service.include_inactive.update_search_index()

    results = list(Service.objects.keyword_search("agefiph"))
    assert results == [best, other]
    assert results[0].search_score > results[1].search_score


def test_keyword_search_thematic_weight():
    other = ServiceFactory(name="Lorem", structure__name="Soutien aux aidants", thematics=[])
    best = ServiceFactory(
        name="Lorem",
        structure__name="Lorem",
        thematics=[GenericReferenceItemFactory(kind="THEMATIC", label="Soutien aux aidants")],
    )
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("soutien aux aidants")) == [best, other]


def test_keyword_search_ordering():
    services = [
        ServiceFactory(name=name, structure__name="Lorem", score_qualite=score_qualite)
        for name, score_qualite in [
            ("France Travail Paris", 0.7),
            ("France Travail Paris", 0.9),
            ("Agence France Travail du 2ème arrondissement de Paris", 0.8),
            ("Agence France Travail du 2ème arrondissement de Paris", 1.0),
        ]
    ]
    Service.include_inactive.update_search_index()

    with assertNumQueries(1):
        results = list(Service.objects.keyword_search("France travail Paris"))
    assert results == [services[1], services[0], services[3], services[2]]
    assert 0 < results[2].search_score < results[0].search_score < 1
