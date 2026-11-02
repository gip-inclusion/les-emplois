import pytest

from itou.insertion.models import Service, WordFrequency
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


def test_update_search_index_refreshes_word_frequencies():
    WordFrequency.objects.create(stem="obsolete", service_count=1)
    ServiceFactory(
        name="Garage solidaire", description="", structure__name="Garage", structure__description="", thematics=[]
    )
    ServiceFactory(name="Garage", description="", structure__name="Mobilité", structure__description="", thematics=[])
    ServiceFactory(name="Inactif", is_active=False, thematics=[])

    Service.include_inactive.update_search_index()

    assert dict(WordFrequency.objects.values_list("stem", "service_count")) == {
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


@pytest.mark.parametrize(
    "best_field,other_field",
    [
        ("name", "structure__name"),
        ("structure__name", "publics_details"),
    ],
)
def test_keyword_search_ranks_by_field_weight(best_field, other_field):
    other = ServiceFactory(**{other_field: "Agefiph"})
    best = ServiceFactory(**{best_field: "Agefiph"})
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("agefiph")) == [best, other]


def test_keyword_search_ranks_thematics_first():
    in_structure_name = ServiceFactory(structure__name="Soutien aux aidants")
    in_thematics = ServiceFactory(
        thematics=[GenericReferenceItemFactory(kind="THEMATIC", label="Soutien aux aidants")],
    )
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("soutien aux aidants")) == [in_thematics, in_structure_name]


@pytest.mark.parametrize(
    "q,expected",
    [
        ("naturalisation", True),
        ("titre de séjour", True),
        ("Titre de Séjour", True),
        ("titre", False),
    ],
)
def test_keyword_search_thematic_aliases(q, expected):
    ServiceFactory(
        thematics=[
            GenericReferenceItemFactory(
                kind="THEMATIC",
                value="difficultes-administratives-ou-juridiques--accompagnement-pour-lacces-a-la-citoyennete",
                label="Citoyenneté",
            )
        ],
    )
    Service.include_inactive.update_search_index()

    assert Service.objects.keyword_search(q).exists() is expected


def test_keyword_search_ranks_multi_word_aliases_as_thematics():
    in_publics_details = ServiceFactory(publics_details="Titre de séjour")
    in_thematic_aliases = ServiceFactory(
        thematics=[
            GenericReferenceItemFactory(
                kind="THEMATIC",
                value="difficultes-administratives-ou-juridiques--accompagnement-pour-lacces-a-la-citoyennete",
                label="Citoyenneté",
            )
        ],
    )
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("titre de séjour")) == [in_thematic_aliases, in_publics_details]


@pytest.mark.parametrize(
    "name,q",
    [
        ("Lutte contre l'illettrisme", "illetrisme"),
        ("Garage solidaire", "garage solidiare"),
    ],
)
def test_keyword_search_tolerates_typos(name, q):
    service = ServiceFactory(name=name)
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search(q)) == [service]


def test_keyword_search_with_typo_also_matches_the_typo():
    correct = ServiceFactory(name="Illettrisme")
    misspelled = ServiceFactory(name="Illetrisme")
    Service.include_inactive.update_search_index()

    assert set(Service.objects.keyword_search("illetrisme")) == {correct, misspelled}


def test_keyword_search_with_typo_still_requires_every_word():
    ServiceFactory(name="Garage solidaire")
    Service.include_inactive.update_search_index()

    assert not Service.objects.keyword_search("garage tracteur").exists()


def test_keyword_search_also_ranks_by_quality():
    slightly_more_relevant = ServiceFactory(name="Garage solidaire", description="Garage", score_qualite=0.2)
    better_quality = ServiceFactory(name="Garage solidaire", score_qualite=0.9)
    far_less_relevant = ServiceFactory(publics_details="Garage solidaire", score_qualite=1)
    Service.include_inactive.update_search_index()

    assert list(Service.objects.keyword_search("garage solidaire")) == [
        better_quality,
        slightly_more_relevant,
        far_less_relevant,
    ]
