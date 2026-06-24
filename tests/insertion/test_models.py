import pytest
from django.contrib.gis.geos import Point

from itou.insertion.models import GenericReferenceItemKind, Service
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
    StructureFactory,
)


@pytest.mark.no_django_db
@pytest.mark.parametrize(
    "address_kwargs,expected",
    [
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            "12 rue des terreaux, Bât. B, 38110 La Tour du Pin",
            id="complete_address",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            "12 rue des terreaux, 38110 La Tour du Pin",
            id="without_address_line_2",
        ),
    ],
)
def test_address_on_one_line(address_kwargs, expected):
    structure = StructureFactory.build(**address_kwargs)
    assert structure.address_on_one_line == expected


@pytest.mark.no_django_db
@pytest.mark.parametrize(
    "address_kwargs",
    [
        pytest.param(
            {
                "address_line_1": "",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "La Tour du Pin",
            },
            id="missing_address_line_1",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "",
                "city": "La Tour du Pin",
            },
            id="missing_post_code",
        ),
        pytest.param(
            {
                "address_line_1": "12 rue des terreaux",
                "address_line_2": "Bât. B",
                "post_code": "38110",
                "city": "",
            },
            id="missing_city",
        ),
    ],
)
def test_address_on_one_line_incomplete_returns_none(address_kwargs):
    structure = StructureFactory.build(**address_kwargs)
    assert structure.address_on_one_line is None


@pytest.mark.parametrize(
    "service_kwargs,expected",
    [
        pytest.param({"is_orientable_with_form": True}, True, id="orientable_with_form"),
        pytest.param(
            {"mobilization_modes_professionals_external_form_link": "https://example.com"},
            True,
            id="external_form_link",
        ),
        pytest.param(
            {
                "is_orientable_with_form": False,
                "mobilization_modes_professionals_external_form_link": "",
            },
            False,
            id="no_orientation_action",
        ),
    ],
)
def test_has_orientation_action(service_kwargs, expected):
    service = ServiceFactory.build(**service_kwargs)
    assert service.has_orientation_action is expected


def _search(vannes, *, reception, thematics=None):
    return Service.objects.search(
        city=vannes,
        thematics=thematics or [THEMATIC_VALUE],
        reception=reception,
        service_types=[],
    )


class TestServiceSearch:
    def test_in_person_within_radius(self):
        vannes = create_city_vannes()
        near = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        ServiceFactory(coordinates=create_city_geispolsheim().coords, city="Geispolsheim")

        results = _search(vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [near]

    def test_in_person_excludes_neighbour_commune_not_covering_city(self):
        vannes = create_city_vannes()
        unspecified = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=[])
        covering = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=["56"])
        ServiceFactory(coordinates=Point(-2.75, 47.70), city="Theix", eligibility_zones=["56251"])

        results = _search(vannes, reception=IN_PERSON_RECEPTION_VALUE)
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

        results = _search(vannes, reception=REMOTE_RECEPTION_VALUE)
        assert set(results) == {nationwide, department, commune, unspecified}

    def test_remote_matched_on_epci(self):
        vannes = create_city_vannes()
        vannes.siren_epci = "200000172"
        epci = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["200000172"])
        epci.receptions.set([RemoteReceptionFactory()])
        other = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["200000999"])
        other.receptions.set([RemoteReceptionFactory()])

        results = _search(vannes, reception=REMOTE_RECEPTION_VALUE)
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

        results = _search(vannes, reception=reception)
        assert {service.uid for service in results} == expected

    def test_filter_on_thematic(self):
        vannes = create_city_vannes()
        match = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        other = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        other.thematics.set([OtherThematicFactory()])

        results = _search(vannes, reception=IN_PERSON_RECEPTION_VALUE)
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
        )
        assert list(results) == [match]

    def test_excludes_services_without_location(self):
        vannes = create_city_vannes()
        located = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        ServiceFactory(coordinates=None, city="Vannes")
        ServiceFactory(coordinates=vannes.coords, city="")

        results = _search(vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [located]

    def test_orders_in_person_first_then_by_distance(self):
        vannes = create_city_vannes()
        remote = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["france"])
        remote.receptions.set([RemoteReceptionFactory()])
        mid = ServiceFactory(coordinates=Point(-2.75, 47.70), city="Vannes")
        close = ServiceFactory(coordinates=vannes.coords, city="Vannes")

        results = _search(vannes, reception="")
        assert list(results) == [close, mid, remote]

    def test_search_does_not_join_genericreferenceitem(self):
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes")

        sql = str(_search(vannes, reception=IN_PERSON_RECEPTION_VALUE).query)
        assert 'INNER JOIN "insertion_genericreferenceitem"' not in sql
        assert "genericreferenceitem_id" in sql
