import pytest
from django.contrib.gis.geos import Point

from itou.insertion.enums import GenericReferenceItemKind
from itou.insertion.models import Service, WordFrequency
from tests.cities.factories import create_city_geispolsheim, create_city_vannes
from tests.insertion.factories import (
    IN_PERSON_RECEPTION_VALUE,
    REMOTE_RECEPTION_VALUE,
    THEMATIC_VALUE,
    GenericReferenceItemFactory,
    InPersonReceptionFactory,
    OtherThematicFactory,
    RemoteReceptionFactory,
    ServiceFactory,
)


class TestServiceFilterSearch:
    def _search(self, *, city, reception, thematics=None):
        return Service.objects.filter_search(
            city=city,
            thematics=thematics or [THEMATIC_VALUE],
            reception=reception,
            service_types=[],
        )

    def test_in_person_within_radius(self):
        vannes = create_city_vannes()
        near = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        ServiceFactory(coordinates=create_city_geispolsheim().coords, city="Geispolsheim")

        results = self._search(city=vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [near]

    def test_in_person_excludes_neighbour_commune_not_covering_city(self):
        vannes = create_city_vannes()
        unspecified = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=[])
        covering = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=["56"])
        ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=["56251"])

        results = self._search(city=vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert set(results) == {unspecified, covering}

    def test_remote_matched_on_eligibility_zones(self):
        vannes = create_city_vannes()
        nationwide = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["france"])
        nationwide.receptions.set([RemoteReceptionFactory()])
        department = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["56"])
        department.receptions.set([RemoteReceptionFactory()])
        commune = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["56260"])
        commune.receptions.set([RemoteReceptionFactory()])
        # An unspecified zone means national availability (aligned on data·inclusion).
        unspecified = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=[])
        unspecified.receptions.set([RemoteReceptionFactory()])
        excluded = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["67"])
        excluded.receptions.set([RemoteReceptionFactory()])

        results = self._search(city=vannes, reception=REMOTE_RECEPTION_VALUE)
        assert set(results) == {nationwide, department, commune, unspecified}

    def test_remote_matched_on_epci(self):
        vannes = create_city_vannes()
        vannes.siren_epci = "200000172"
        epci = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["200000172"])
        epci.receptions.set([RemoteReceptionFactory()])
        other = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["200000999"])
        other.receptions.set([RemoteReceptionFactory()])

        results = self._search(city=vannes, reception=REMOTE_RECEPTION_VALUE)
        assert set(results) == {epci}

    @pytest.mark.parametrize(
        "reception,expected",
        [
            (IN_PERSON_RECEPTION_VALUE, {"presentiel", "mixte"}),
            (REMOTE_RECEPTION_VALUE, {"distanciel", "mixte"}),
            ("", {"presentiel", "distanciel", "mixte"}),
        ],
    )
    def test_filter_on_reception(self, reception, expected):
        vannes = create_city_vannes()
        ServiceFactory(uid="presentiel", coordinates=vannes.coords, city="Vannes")
        distanciel = ServiceFactory(
            uid="distanciel", coordinates=vannes.coords, city="Vannes", eligibility_zones=["56"]
        )
        distanciel.receptions.set([RemoteReceptionFactory()])
        mixte = ServiceFactory(uid="mixte", coordinates=vannes.coords, city="Vannes", eligibility_zones=["56"])
        mixte.receptions.set([InPersonReceptionFactory(), RemoteReceptionFactory()])

        results = self._search(city=vannes, reception=reception)
        assert {service.uid for service in results} == expected

    def test_filter_on_thematic(self):
        vannes = create_city_vannes()
        match = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        other = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        other.thematics.set([OtherThematicFactory()])

        results = self._search(city=vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [match]

    def test_filter_on_service_type(self):
        vannes = create_city_vannes()
        accompagnement = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.SERVICE_KIND, value="accompagnement"
        )
        formation = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SERVICE_KIND, value="formation")
        match = ServiceFactory(kind=accompagnement, coordinates=vannes.coords, city="Vannes")
        ServiceFactory(kind=formation, coordinates=vannes.coords, city="Vannes")

        results = Service.objects.search(
            city=vannes,
            thematics=[THEMATIC_VALUE],
            reception=IN_PERSON_RECEPTION_VALUE,
            service_types=["accompagnement"],
            keyword=None,
        )
        assert list(results) == [match]

    def test_excludes_services_without_location(self):
        vannes = create_city_vannes()
        located = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        ServiceFactory(coordinates=None, city="Vannes")
        ServiceFactory(coordinates=vannes.coords, city="")

        results = self._search(city=vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [located]

    def test_search_does_not_join_genericreferenceitem(self):
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes")

        sql = str(self._search(city=vannes, reception=IN_PERSON_RECEPTION_VALUE).query)
        assert 'INNER JOIN "insertion_genericreferenceitem"' not in sql
        assert "genericreferenceitem_id" in sql


class TestServiceKeywordSearch:
    def test_update_search_index(self):
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
            "'meti':3A 'person':17B,20C 'reconvers':4A 'repar':12B 'san':21C 'solidair':6A 'travail':10B "
            "'vehicul':14B 'zzdecouvertemetier':7A 'zzforummetiers':8A"
        )

    def test_update_search_index_without_thematics_nor_publics(self):
        service = ServiceFactory(name="Garage solidaire", thematics=[])

        Service.include_inactive.update_search_index()

        service.refresh_from_db()
        assert "'garag':1A" in service.search_vector

    def test_update_search_index_refreshes_word_frequencies(self):
        WordFrequency.objects.create(stem="obsolete", service_count=1)
        ServiceFactory(
            name="Garage solidaire", description="", structure__name="Garage", structure__description="", thematics=[]
        )
        ServiceFactory(
            name="Garage", description="", structure__name="Mobilité", structure__description="", thematics=[]
        )
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
    def test_keyword_search_by_field(self, field, value):
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
    def test_keyword_search_by_reference_item(self, relation, kind):
        service = ServiceFactory(**{relation: [GenericReferenceItemFactory(kind=kind, label="Agefiph")]})
        ServiceFactory()
        Service.include_inactive.update_search_index()

        assert list(Service.objects.keyword_search("agefiph")) == [service]

    def test_keyword_search_ignores_receptions(self):
        ServiceFactory(receptions=[GenericReferenceItemFactory(kind="RECEPTION", label="Agefiph")])
        Service.include_inactive.update_search_index()

        assert not Service.objects.keyword_search("agefiph").exists()

    def test_keyword_search_requires_every_word(self):
        ServiceFactory(name="Garage solidaire")
        Service.include_inactive.update_search_index()

        assert Service.objects.keyword_search("garage solidaire").exists()
        assert not Service.objects.keyword_search("garage associatif").exists()

    @pytest.mark.parametrize("name,q", [("Mobilité", "mobilite"), ("Mobilite", "mobilité")])
    def test_keyword_search_ignores_accents(self, name, q):
        service = ServiceFactory(name=name)
        Service.include_inactive.update_search_index()

        assert list(Service.objects.keyword_search(q)) == [service]

    def test_keyword_search_hyphenated_word(self):
        service = ServiceFactory(name="Location de deux-roues", thematics=[])
        Service.include_inactive.update_search_index()

        assert list(Service.objects.keyword_search("deux-roues")) == [service]

    @pytest.mark.parametrize("q", ["", "   ", "le", "de la"])
    def test_keyword_search_without_any_word(self, q):
        ServiceFactory(name="Le garage de la ville")
        Service.include_inactive.update_search_index()

        assert not Service.objects.keyword_search(q).exists()

    @pytest.mark.parametrize(
        "q,expected",
        [
            ("naturalisation", True),
            ("titre de séjour", True),
            ("Titre de Séjour", True),
            ("titre", False),
        ],
    )
    def test_keyword_search_thematic_aliases(self, q, expected):
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

    @pytest.mark.parametrize(
        "name,q",
        [
            ("Lutte contre l'illettrisme", "illetrisme"),
            ("Garage solidaire", "garage solidiare"),
        ],
    )
    def test_keyword_search_tolerates_typos(self, name, q):
        service = ServiceFactory(name=name)
        Service.include_inactive.update_search_index()

        assert list(Service.objects.keyword_search(q)) == [service]

    def test_keyword_search_with_typo_also_matches_the_typo(self):
        correct = ServiceFactory(name="Illettrisme")
        misspelled = ServiceFactory(name="Illetrisme")
        Service.include_inactive.update_search_index()

        assert set(Service.objects.keyword_search("illetrisme")) == {correct, misspelled}

    def test_keyword_search_with_typo_still_requires_every_word(self):
        ServiceFactory(name="Garage solidaire")
        Service.include_inactive.update_search_index()

        assert not Service.objects.keyword_search("garage tracteur").exists()


class TestMixedSearchAndOrder:
    def _search(self, *, city=None, keyword=None, thematics=[THEMATIC_VALUE], reception=""):
        return Service.objects.search(
            city=city, thematics=thematics, reception=reception, service_types=[], keyword=keyword
        )

    def test_filter_search_orders_in_person_first_then_by_distance(self):
        vannes = create_city_vannes()
        remote = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["france"])
        remote.receptions.set([RemoteReceptionFactory()])
        mid = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Vannes")
        close = ServiceFactory(coordinates=vannes.coords, city="Vannes")

        results = self._search(city=vannes, reception="")
        assert list(results) == [close, mid, remote]

    @pytest.mark.parametrize(
        "best_field,other_field",
        [
            ("name", "structure__name"),
            ("structure__name", "publics_details"),
        ],
    )
    def test_keyword_search_ranks_by_field_weight(self, best_field, other_field):
        other = ServiceFactory(**{other_field: "Agefiph"})
        best = ServiceFactory(**{best_field: "Agefiph"})
        Service.include_inactive.update_search_index()

        assert list(self._search(keyword="agefiph")) == [best, other]

    def test_keyword_search_ranks_thematics_first(self):
        second_thematic_value = "famille--soutien-aidants"
        in_structure_name = ServiceFactory(structure__name="Soutien aux aidants")
        in_thematics = ServiceFactory(
            thematics=[
                GenericReferenceItemFactory(kind="THEMATIC", label="Soutien aux aidants", value=second_thematic_value)
            ],
        )
        Service.include_inactive.update_search_index()

        assert list(
            self._search(keyword="soutien aux aidants", thematics=[THEMATIC_VALUE, second_thematic_value])
        ) == [in_thematics, in_structure_name]

    def test_keyword_search_ranks_multi_word_aliases_as_thematics(self):
        second_thematic_value = (
            "difficultes-administratives-ou-juridiques--accompagnement-pour-lacces-a-la-citoyennete"
        )
        in_publics_details = ServiceFactory(publics_details="Titre de séjour")
        in_thematic_aliases = ServiceFactory(
            thematics=[
                GenericReferenceItemFactory(
                    kind="THEMATIC",
                    value=second_thematic_value,
                    label="Citoyenneté",
                )
            ],
        )
        Service.include_inactive.update_search_index()

        assert list(self._search(keyword="titre de séjour", thematics=[THEMATIC_VALUE, second_thematic_value])) == [
            in_thematic_aliases,
            in_publics_details,
        ]

    def test_keyword_search_also_ranks_by_quality(self):
        slightly_more_relevant = ServiceFactory(name="Garage solidaire", description="Garage", score_qualite=0.2)
        better_quality = ServiceFactory(name="Garage solidaire", score_qualite=0.9)
        far_less_relevant = ServiceFactory(publics_details="Garage solidaire", score_qualite=1)
        Service.include_inactive.update_search_index()

        assert list(self._search(keyword="garage solidaire")) == [
            better_quality,
            slightly_more_relevant,
            far_less_relevant,
        ]

    def test_mixed_search_orders_distance_and_match(self):
        thematic = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.THEMATIC, value="famille--soutien-aidants", label="Soutien aux aidants"
        )
        vannes = create_city_vannes()

        third_match = ServiceFactory(
            thematics=[thematic],
            description="Super-aidants",
            coordinates=vannes.coords,
            city="Vannes",
        )
        second_match = ServiceFactory(
            thematics=[thematic],
            name="Super-aidants",
            coordinates=Point(-2.75, 47.70),  # within SERVICE_SEARCH_RADIUS_KM
            city="Theix",
            eligibility_zones=["56"],
        )
        first_match_remote = ServiceFactory(
            thematics=[thematic],
            name="Super-aidants",
            coordinates=vannes.coords,
            city="Vannes",
        )
        first_match_remote.receptions.set([RemoteReceptionFactory()])
        # no match
        ServiceFactory(
            thematics=[
                GenericReferenceItemFactory(
                    kind=GenericReferenceItemKind.THEMATIC,
                    value="choisir-un-metier--confirmer-son-choix-de-metier",
                    label="Confirmer son choix de métier",
                )
            ],
            name="Super-aidants",
            coordinates=vannes.coords,
            city="Vannes",
        )
        ServiceFactory(
            thematics=[thematic],
            name="Super-aidants",
            coordinates=create_city_geispolsheim().coords,
            city="Geispolsheim",
        )
        Service.include_inactive.update_search_index()

        # No keyword search -- order: distance then pk, remote at the end
        assert list(
            self._search(
                city=vannes,
                thematics=[thematic.value],
                reception="",
                keyword=None,
            )
        ) == [third_match, second_match, first_match_remote]

        # Keyword search -- order: distance + text search score (more weight on name than description) then pk
        assert list(
            self._search(
                city=vannes,
                thematics=[thematic.value],
                reception="",
                keyword="Super-aidants",
            )
        ) == [first_match_remote, second_match, third_match]

    def test_mixed_search_city_only_returns_all_services(self):
        vannes = create_city_vannes()

        in_person = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        remote = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        remote.receptions.set([RemoteReceptionFactory()])

        # Won’t be in the results
        ServiceFactory(coordinates=vannes.coords, city="Vannes", is_active=False)
        ServiceFactory(coordinates=create_city_geispolsheim().coords, city="Geispolsheim")
        ServiceFactory(coordinates=vannes.coords, city="")

        assert list(self._search(city=vannes)) == [in_person, remote]

    def test_mixed_search_keyword_only_returns_all_services(self):
        vannes = create_city_vannes()

        service_vannes = ServiceFactory(coordinates=vannes.coords, city="Vannes", name="véhicule")
        service_geispolsheim = ServiceFactory(
            coordinates=create_city_geispolsheim().coords, city="Geispolsheim", structure__name="véhicule"
        )
        service_remote = ServiceFactory(coordinates=vannes.coords, city="Vannes", name="véhicule")
        service_remote.receptions.set([RemoteReceptionFactory()])
        service_no_coords = ServiceFactory()  # thematic value contains 'véhicule'

        # Won’t be in the results
        ServiceFactory(name="véhicule", is_active=False)

        Service.include_inactive.update_search_index()

        assert set(self._search(keyword="véhicule")) == {
            service_vannes,
            service_geispolsheim,
            service_remote,
            service_no_coords,
        }
