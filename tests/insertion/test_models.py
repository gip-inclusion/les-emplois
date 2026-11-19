import datetime
import hashlib
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from freezegun import freeze_time

from itou.insertion.enums import MobilizationEventKind
from itou.insertion.models import MobilizationEvent, Service
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory
from tests.insertion.factories import (
    IN_PERSON_RECEPTION_VALUE,
    THEMATIC_VALUE,
    MobilizationEmailFactory,
    MobilizationEventFactory,
    ServiceFactory,
    StructureFactory,
)
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory, ProfessionalFactory


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
    "contact_email,lien_mobilisation, non_orientable_sources, expected",
    [
        ("contact@example.com", "", [], True),
        ("", "", [], False),
        ("", "https://ext.link", [], False),
        ("", "", ["blacklisted-source"], False),
        ("", "https://ext.link", ["blacklisted-source"], False),
        ("contact@example.com", "https://ext.link", ["blacklisted-source"], False),
    ],
)
def test_is_orientable_via_internal_form(contact_email, lien_mobilisation, non_orientable_sources, expected, settings):
    settings.NON_ORIENTABLE_DI_SOURCES = non_orientable_sources
    service = ServiceFactory(
        contact_email=contact_email, lien_mobilisation=lien_mobilisation, source__value="blacklisted-source"
    )

    assert service.is_orientable_via_internal_form is expected


def test_lien_mobilisation_must_be_url():
    service = ServiceFactory.build(lien_mobilisation="not-a-url")

    with pytest.raises(ValidationError):
        service.full_clean()


@pytest.mark.parametrize(
    "lien_mobilisation, is_from_non_orientation_di_source, contact_phone, contact_email, expected",
    [
        pytest.param(
            "https://ext.link",
            False,
            "3949",
            "contact@email.fake",
            ["Site web de la structure", "Téléphone", "Email"],
            id="full_with_ext_link",
        ),
        pytest.param(
            "", False, "3949", "contact@email.fake", ["Formulaire", "Téléphone", "Email"], id="full_with_form"
        ),
        pytest.param("", False, "", "contact@example.com", ["Formulaire", "Email"], id="form_and_email"),
        pytest.param("", True, "3949", "contact@email.fake", ["Téléphone", "Email"], id="no_ext_link_no_form"),
        pytest.param("", True, "", "", [], id="nothing"),
    ],
)
def test_display_mobilization_modes(
    lien_mobilisation,
    is_from_non_orientation_di_source,
    contact_phone,
    contact_email,
    expected,
    settings,
):

    service = ServiceFactory(
        lien_mobilisation=lien_mobilisation, contact_phone=contact_phone, contact_email=contact_email
    )

    if is_from_non_orientation_di_source:
        settings.NON_ORIENTABLE_DI_SOURCES = [service.source.value]

    assert service.display_mobilization_modes == expected


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
            (ProfessionalFactory, PrescriberOrganizationFactory),
            (ProfessionalFactory, CompanyFactory),
            (JobSeekerFactory, None),
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
        session_key = "session123"
        hashed_session_key = hashlib.sha256(session_key.encode()).hexdigest()
        MobilizationEvent.objects.create_mobilization_event(
            session_key=session_key,
            user=user,
            kind=kind,
            organization=organization,
            structure=StructureFactory(),
            service=service,
        )

        assert MobilizationEvent.objects.filter(hashed_session_key=hashed_session_key, kind=kind).count() == 1

    def test_create_mobilization_event_bad_user_kind(self):
        for user in [ItouStaffFactory(), ProfessionalFactory()]:
            MobilizationEvent.objects.create_mobilization_event(
                session_key="session123",
                kind=MobilizationEventKind.STRUCTURE_CONTACT,
                user=user,
                organization=None,
                structure=StructureFactory(),
                service=ServiceFactory(),
            )
        assert not MobilizationEvent.objects.exists()


class TestMobilizationEmail:
    def test_sender_organization_coherence(self):
        prescriber_organization = PrescriberOrganizationFactory()
        company = CompanyFactory()
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*sender_organization_coherence.*"):
                MobilizationEmailFactory(sender_prescriber_organization=None, sender_company=None)
        with transaction.atomic():
            with pytest.raises(IntegrityError, match=r".*sender_organization_coherence.*"):
                MobilizationEmailFactory(
                    sender_prescriber_organization=prescriber_organization, sender_company=company
                )

        MobilizationEmailFactory(sender_prescriber_organization=prescriber_organization, sender_company=None)
        MobilizationEmailFactory(sender_prescriber_organization=None, sender_company=company)


class TestIsActiveManager:
    def test_both_managers(self):
        active = ServiceFactory()
        inactive = ServiceFactory(is_active=False)

        assert set(Service.objects.all()) == {active}
        assert set(Service.include_inactive.all()) == {active, inactive}

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

        results = Service.objects.search(
            city=vannes,
            thematics=[THEMATIC_VALUE],
            reception=IN_PERSON_RECEPTION_VALUE,
            service_types=[],
            keyword=None,
        )
        assert list(results) == [active]


@pytest.mark.parametrize(
    "today,updated_on,expected",
    [
        (datetime.date(2025, 4, 15), datetime.date(2025, 1, 15), False),
        (datetime.date(2025, 10, 15), datetime.date(2025, 1, 15), True),
    ],
)
def test_service_is_update_needed(today, updated_on, expected):
    service = ServiceFactory.build(updated_on=updated_on)
    with freeze_time(today):
        assert service.is_update_needed is expected


def test_generate_extra_credential_documents_info():
    service = ServiceFactory(
        extra={
            "forms": [
                {"name": "my_form.pdf", "url": "production/eed8a0d4-238d-4921-a133-f5895e79fafb/my_form.pdf"},
            ]
        }
    )

    with patch(
        "itou.insertion.models.generate_dora_storage_url",
        return_value="https://s3.example.com/my_form.pdf?token=aaa",
    ) as mock_generate_url:
        assert service.generate_extra_credential_documents_info() == [
            ("my_form.pdf", "https://s3.example.com/my_form.pdf?token=aaa")
        ]
        mock_generate_url.assert_called_once_with("production/eed8a0d4-238d-4921-a133-f5895e79fafb/my_form.pdf")


def test_generate_extra_credential_documents_info_without_extra():
    service = ServiceFactory(extra=None)

    assert service.generate_extra_credential_documents_info() == []
