import random

import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.nexus.enums import Auth, Service
from itou.nexus.models import DEFAULT_VALID_SINCE, ActivatedService, NexusRessourceSyncStatus
from itou.nexus.utils import (
    build_user,
    complete_full_sync,
    dropdown_status,
    get_service_users,
    init_full_sync,
    serialize_user,
)
from itou.users.enums import IdentityProvider
from tests.companies.factories import CompanyMembershipFactory
from tests.nexus.factories import NexusMembershipFactory, NexusRessourceSyncStatusFactory, NexusUserFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


def test_init_full_sync():
    with freeze_time() as frozen_time:
        started_at = init_full_sync(Service.DORA)
        assert started_at == timezone.now()
        # NB: I used timezone.now() because frozen_time().isoformat() is missing the tz

        api_sync = NexusRessourceSyncStatus.objects.get()
        assert api_sync.service == Service.DORA
        assert api_sync.valid_since == DEFAULT_VALID_SINCE
        assert api_sync.in_progress_since == timezone.now()

        # Update existing NexusRessourceSyncStatus
        frozen_time.tick()
        started_at = init_full_sync(Service.DORA)
        assert started_at == timezone.now()

        updated_api_sync = NexusRessourceSyncStatus.objects.get()
        assert updated_api_sync.service == Service.DORA
        assert updated_api_sync.valid_since == DEFAULT_VALID_SINCE
        assert updated_api_sync.in_progress_since == timezone.now()
        assert updated_api_sync.in_progress_since != api_sync.in_progress_since


def test_complete_full_sync():
    start_at = timezone.now()
    NexusRessourceSyncStatusFactory(service=Service.DORA, in_progress_since=start_at)

    assert complete_full_sync(Service.DORA, timezone.now()) is False  # Wrong started_at
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.in_progress_since == start_at
    assert complete_full_sync(Service.EMPLOIS, timezone.now()) is False  # Wrong service
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.in_progress_since == start_at

    assert complete_full_sync(Service.DORA, start_at) is True
    api_synced = NexusRessourceSyncStatus.objects.get()
    assert api_synced.service == Service.DORA
    assert api_synced.valid_since == start_at
    assert api_synced.in_progress_since is None


class TestGetServiceUsers:
    def test_only_one_kwarg(self):
        with pytest.raises(AssertionError):
            get_service_users()

        user = PrescriberFactory()

        with pytest.raises(AssertionError):
            get_service_users(email=user.email, user=user)

    def test_emplois_user(self):
        user = PrescriberFactory()
        expected = [build_user(serialize_user(user), Service.EMPLOIS)]
        assert get_service_users(user=user) == expected
        assert get_service_users(email=user.email) == expected

    def test_activated_services(self):
        user = PrescriberFactory()
        activated_service = ActivatedService.objects.create(
            user=user, service=random.choice([Service.PILOTAGE, Service.MON_RECAP])
        )

        expected = [
            build_user(serialize_user(user), Service.EMPLOIS),
            build_user(serialize_user(user), activated_service.service),
        ]
        assert get_service_users(user=user) == expected
        assert get_service_users(email=user.email) == expected

    def test_nexus_user(self):
        nexus_user = NexusUserFactory()

        assert get_service_users(email=nexus_user.email) == [nexus_user]

    def test_wrong_emplois_user(self):
        for factory in [JobSeekerFactory, ItouStaffFactory, LaborInspectorFactory]:
            user = factory()
            assert get_service_users(email=user.email) == []


class TestDropDownStatus:
    @pytest.mark.parametrize("pc_on_emplois", [True, False])
    @pytest.mark.parametrize("pc_on_service", [True, False])
    def test_proconnect(self, pc_on_emplois, pc_on_service):
        user = PrescriberFactory(
            identity_provider=IdentityProvider.PRO_CONNECT if pc_on_emplois else IdentityProvider.DJANGO
        )
        NexusUserFactory(email=user.email, auth=Auth.MAGIC_LINK, source=Service.DORA)
        NexusUserFactory(email=user.email, auth=Auth.DJANGO, source=Service.MARCHE)
        if pc_on_service:
            NexusUserFactory(email=user.email, auth=Auth.PRO_CONNECT, source=Service.PILOTAGE)

        assert dropdown_status(user=user)["proconnect"] == (pc_on_emplois or pc_on_service)
        assert dropdown_status(email=user.email)["proconnect"] == (pc_on_emplois or pc_on_service)

    def test_mvp_enabled_prescriber(self):
        user = PrescriberFactory()
        assert dropdown_status(user=user)["mvp_enabled"] is False
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        PrescriberMembershipFactory(user=user, organization__department=75)
        assert dropdown_status(user=user)["mvp_enabled"] is False
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        PrescriberMembershipFactory(user=user, organization__department=random.choice(settings.NEXUS_MVP_DEPARTMENTS))
        assert dropdown_status(user=user)["mvp_enabled"] is True
        assert dropdown_status(email=user.email)["mvp_enabled"] is True

    def test_mvp_enabled_employer(self):
        user = EmployerFactory()
        assert dropdown_status(user=user)["mvp_enabled"] is False
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        CompanyMembershipFactory(user=user, company__department=75)
        assert dropdown_status(user=user)["mvp_enabled"] is False
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        CompanyMembershipFactory(user=user, company__department=random.choice(settings.NEXUS_MVP_DEPARTMENTS))
        assert dropdown_status(user=user)["mvp_enabled"] is True
        assert dropdown_status(email=user.email)["mvp_enabled"] is True

    def test_mvp_enabled_external_service(self):
        user = NexusUserFactory()
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        NexusMembershipFactory(user=user, structure__department=75)
        assert dropdown_status(email=user.email)["mvp_enabled"] is False

        NexusMembershipFactory(user=user, structure__department=random.choice(settings.NEXUS_MVP_DEPARTMENTS))
        assert dropdown_status(email=user.email)["mvp_enabled"] is True

    def test_activated_service(self):
        user = PrescriberFactory()
        expected = [Service.EMPLOIS]
        assert dropdown_status(user=user)["activated_services"] == expected
        assert dropdown_status(email=user.email)["activated_services"] == expected

        activated_service = ActivatedService.objects.create(
            user=user, service=random.choice([Service.PILOTAGE, Service.MON_RECAP])
        )
        expected = [Service.EMPLOIS, activated_service.service]
        assert dropdown_status(user=user)["activated_services"] == expected
        assert dropdown_status(email=user.email)["activated_services"] == expected

        nexus_user = NexusUserFactory(email=user.email, source=random.choice([Service.DORA, Service.MARCHE]))
        expected = sorted([Service.EMPLOIS, activated_service.service, nexus_user.source])
        assert dropdown_status(user=user)["activated_services"] == expected
        assert dropdown_status(email=user.email)["activated_services"] == expected

        user.delete()
        assert dropdown_status(email=nexus_user.email)["activated_services"] == [nexus_user.source]
