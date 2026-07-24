import random

import pytest
from allauth.account.adapter import AnonymousUser
from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction

from itou.insertion.enums import MobilizationEventKind
from itou.insertion.models import GenericReferenceItemKind, MobilizationEvent, Service
from tests.cities.factories import create_city_geispolsheim, create_city_vannes
from tests.companies.factories import CompanyFactory
from tests.insertion.factories import (
    IN_PERSON_RECEPTION_VALUE,
    REMOTE_RECEPTION_VALUE,
    THEMATIC_VALUE,
    GenericReferenceItemFactory,
    InPersonReceptionFactory,
    MobilizationEventFactory,
    OtherThematicFactory,
    RemoteReceptionFactory,
    ServiceFactory,
    StructureFactory,
)
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
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


class TestMobilizationEvent:
    def test_structure_not_null(self):
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*null value in column \"structure_id\".*"):
                MobilizationEventFactory(
                    structure=None, service=ServiceFactory(), kind=MobilizationEventKind.SERVICE_CONTACT
                )

        # No integrity error
        MobilizationEventFactory(
            structure=StructureFactory(), service=ServiceFactory(), kind=MobilizationEventKind.SERVICE_CONTACT
        )

    def test_service_and_structure_kind_coherence(self):
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*service_and_structure_kind_coherence.*"):
                MobilizationEventFactory(service=ServiceFactory())

        # No integrity error
        MobilizationEventFactory(service=ServiceFactory(), kind=MobilizationEventKind.SERVICE_CONTACT)

    def test_authenticated_user_has_organization(self):
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*authenticated_user_has_organization.*"):
                MobilizationEventFactory(user=None, company=CompanyFactory())
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*authenticated_user_has_organization.*"):
                MobilizationEventFactory(user=None, prescriber_organization=PrescriberOrganizationFactory())

        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*authenticated_user_has_organization.*"):
                MobilizationEventFactory(user=EmployerFactory())

    def test_service_external_link_coherence(self):
        service = ServiceFactory()

        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*service_external_link_coherence.*"):
                MobilizationEventFactory(
                    kind=MobilizationEventKind.SERVICE_EXT_LINK, service=service, service_external_link=""
                )
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*service_external_link_coherence.*"):
                MobilizationEventFactory(
                    kind=MobilizationEventKind.SERVICE_CONTACT,
                    service=service,
                    service_external_link="https://site.fake",
                )
        MobilizationEventFactory(
            kind=MobilizationEventKind.SERVICE_EXT_LINK, service=service, service_external_link="https://site.fake"
        )

    @pytest.mark.parametrize(
        "user_factory,organization_factory",
        [
            (None, None),
            (PrescriberFactory, PrescriberOrganizationFactory),
            (EmployerFactory, CompanyFactory),
        ],
    )
    @pytest.mark.parametrize(
        "kind,service_factory",
        [
            (MobilizationEventKind.STRUCTURE_CONTACT, None),
            (MobilizationEventKind.SERVICE_CONTACT, ServiceFactory),
        ],
    )
    def test_create_mobilization_event(self, kind, user_factory, organization_factory, service_factory):
        user = user_factory() if user_factory else AnonymousUser()
        service = service_factory() if service_factory else None
        organization = organization_factory() if organization_factory else None
        MobilizationEvent.objects.create_mobilization_event(
            session_key="session123",
            user=user,
            kind=kind,
            organization=organization,
            structure=StructureFactory(),
            service=service,
        )

        assert MobilizationEvent.objects.filter(session_key="session123", kind=kind).count() == 1

    def test_create_mobilization_event_bad_user_kind(self):
        user = random.choice([JobSeekerFactory(), ItouStaffFactory(), LaborInspectorFactory()])
        MobilizationEvent.objects.create_mobilization_event(
            session_key="session123",
            kind=MobilizationEventKind.STRUCTURE_CONTACT,
            user=user,
            organization=None,
            structure=StructureFactory(),
            service=ServiceFactory(),
        )

        assert not MobilizationEvent.objects.exists()


class TestIsActiveManager:
    def test_both_managers(self):
        active = ServiceFactory()
        inactive = ServiceFactory(is_active=False)

        assert set(Service.objects.all()) == {active}
        assert set(Service.all_objects.all()) == {active, inactive}

    def test_structure_services_excludes_inactive(self):
        structure = StructureFactory()
        active = ServiceFactory(structure=structure)
        ServiceFactory(structure=structure, is_active=False)

        assert set(structure.services.all()) == {active}

    def test_search_only_active_services(self):
        vannes = create_city_vannes()
        active = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        # inactive one
        ServiceFactory(coordinates=vannes.coords, city="Vannes", is_active=False)

        results = _search(vannes, reception=IN_PERSON_RECEPTION_VALUE)
        assert list(results) == [active]
