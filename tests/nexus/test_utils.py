import pytest
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.nexus.enums import Role, Service
from itou.nexus.models import DEFAULT_VALID_SINCE, NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.nexus.utils import (
    build_membership,
    build_structure,
    build_user,
    complete_full_sync,
    init_full_sync,
    serialize_membership,
    serialize_structure,
    serialize_user,
    sync_memberships,
    sync_structures,
    sync_users,
)
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.nexus.factories import NexusRessourceSyncStatusFactory
from tests.nexus.utils import assert_structure_equals, assert_user_equals
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


class TestUsers:
    def test_sync_users(self):
        with freeze_time() as frozen_time:
            user = EmployerFactory()
            assert sync_users([build_user(serialize_user(user), Service.EMPLOIS)]) == 1
            nexus_user = NexusUser.objects.get()
            assert_user_equals(nexus_user, user, Service.EMPLOIS)

            # Change all fields except source id (yes, it's a bit extreme)
            frozen_time.tick()
            updated_user = PrescriberFactory.build()
            updated_user.pk = user.pk
            assert sync_users([build_user(serialize_user(updated_user), Service.EMPLOIS)]) == 1
            updated_nexus_user = NexusUser.objects.get()
            assert_user_equals(updated_nexus_user, updated_user, Service.EMPLOIS)

    def test_sync_users_update_only(self):
        with freeze_time() as frozen_time:
            user = EmployerFactory()
            assert sync_users([build_user(serialize_user(user), Service.PILOTAGE)], update_only=True) == 0
            nexus_user_qs = NexusUser.objects.filter(source=Service.PILOTAGE)
            assert nexus_user_qs.count() == 0

            frozen_time.tick()
            assert sync_users([build_user(serialize_user(user), Service.PILOTAGE)]) == 1
            assertQuerySetEqual(nexus_user_qs.values_list("pk", flat=True), [f"pilotage--{user.pk}"])
            assert set(nexus_user_qs.values_list("updated_at", flat=True)) == {timezone.now()}

            frozen_time.tick()
            new_user = PrescriberFactory()
            assert (
                sync_users(
                    [build_user(serialize_user(u), Service.PILOTAGE) for u in [user, new_user]], update_only=True
                )
                == 1
            )
            assertQuerySetEqual(nexus_user_qs.values_list("pk", flat=True), [f"pilotage--{user.pk}"])
            assert set(nexus_user_qs.values_list("updated_at", flat=True)) == {timezone.now()}

            frozen_time.tick()
            assert sync_users([build_user(serialize_user(u), Service.PILOTAGE) for u in [user, new_user]]) == 2
            assertQuerySetEqual(
                nexus_user_qs.values_list("pk", flat=True),
                [f"pilotage--{user.pk}", f"pilotage--{new_user.pk}"],
                ordered=False,
            )
            assert set(nexus_user_qs.values_list("updated_at", flat=True)) == {timezone.now()}

    def test_sync_users_old_instances(self):
        with freeze_time() as frozen_time:
            user = EmployerFactory()
            assert sync_users([build_user(serialize_user(user), Service.EMPLOIS)]) == 1
            assert NexusUser.objects.get().updated_at == timezone.now()

            frozen_time.tick()
            NexusRessourceSyncStatusFactory(service=Service.EMPLOIS)
            assert NexusUser.objects.exists() is False
            assert sync_users([build_user(serialize_user(user), Service.EMPLOIS)]) == 1
            assert NexusUser.objects.get().updated_at == timezone.now()

            frozen_time.tick()
            NexusRessourceSyncStatus.objects.update(valid_since=timezone.now())
            assert sync_users([build_user(serialize_user(user), Service.EMPLOIS)], update_only=True) == 1
            assert NexusUser.objects.get().updated_at == timezone.now()

    def test_build_user_invalid_kind(self, caplog):
        user = JobSeekerFactory()
        nexus_user = build_user(serialize_user(user), Service.EMPLOIS)
        assert nexus_user.kind == ""
        assert caplog.messages == ["Invalid user kind=job_seeker"]


class TestMemberships:
    @pytest.mark.parametrize("factory", [CompanyMembershipFactory, PrescriberMembershipFactory])
    def test_sync_memberships_nominal(self, factory):
        with freeze_time() as frozen_time:
            membership = factory()
            structure = membership.company if factory == CompanyMembershipFactory else membership.organization
            sync_users([build_user(serialize_user(membership.user), Service.EMPLOIS)])
            sync_structures([build_structure(serialize_structure(structure), Service.EMPLOIS)])

            assert sync_memberships([build_membership(serialize_membership(membership), Service.EMPLOIS)]) == 1
            nexus_membership = NexusMembership.objects.get()
            assert nexus_membership.structure_id == f"emplois-de-linclusion--{structure.uid}"
            assert nexus_membership.user_id == f"emplois-de-linclusion--{membership.user_id}"
            assert nexus_membership.role == Role.ADMINISTRATOR
            assert nexus_membership.updated_at == timezone.now()

            frozen_time.tick()
            membership.is_admin = False
            assert sync_memberships([build_membership(serialize_membership(membership), Service.EMPLOIS)]) == 1
            updated_nexus_membership = NexusMembership.objects.get()
            assert updated_nexus_membership.role == Role.COLLABORATOR
            assert updated_nexus_membership.updated_at == timezone.now()
            assert updated_nexus_membership.updated_at != nexus_membership.updated_at

    def test_sync_memberships_old_instances(self):
        with freeze_time() as frozen_time:
            membership = CompanyMembershipFactory()
            sync_users([build_user(serialize_user(membership.user), Service.EMPLOIS)])
            sync_structures([build_structure(serialize_structure(membership.company), Service.EMPLOIS)])

            assert sync_memberships([build_membership(serialize_membership(membership), Service.EMPLOIS)]) == 1
            assert NexusMembership.objects.get().updated_at == timezone.now()

            frozen_time.tick()
            NexusRessourceSyncStatusFactory(service=Service.EMPLOIS)
            assert NexusMembership.objects.exists() is False
            assert sync_memberships([build_membership(serialize_membership(membership), Service.EMPLOIS)]) == 1
            assert NexusMembership.objects.get().updated_at == timezone.now()

    def test_build_structure_invalid_kind(self, caplog):
        structure = CompanyFactory()
        structure.kind = "bad_kind"

        nexus_structure = build_structure(serialize_structure(structure), Service.EMPLOIS)
        assert nexus_structure.kind == ""
        assert caplog.messages == ["Invalid structure kind=bad_kind"]


class TestStructures:
    @pytest.mark.parametrize(
        "factory,kwargs",
        [
            (CompanyFactory, {}),
            (PrescriberOrganizationFactory, {}),
            (PrescriberOrganizationFactory, {"authorized": False}),
        ],
        ids=["company", "authorized_prescriber_org", "prescriber_org"],
    )
    def test_sync_structures_nominal(self, factory, kwargs):
        with freeze_time() as frozen_time:
            structure = factory(**kwargs)

            assert sync_structures([build_structure(serialize_structure(structure), Service.EMPLOIS)]) == 1
            nexus_structure = NexusStructure.objects.get()
            assert_structure_equals(nexus_structure, structure, Service.EMPLOIS)
            assert nexus_structure.updated_at == timezone.now()

            # Change all fields except source id (yes, it's a bit extreme)
            frozen_time.tick()
            updated_structure = factory.build(**kwargs)
            updated_structure.uid = structure.uid
            updated_structure.pk = structure.pk  # We need a pk for the source_link
            assert sync_structures([build_structure(serialize_structure(updated_structure), Service.EMPLOIS)]) == 1
            updated_nexus_structure = NexusStructure.objects.get()
            assert_structure_equals(updated_nexus_structure, updated_structure, Service.EMPLOIS)
            assert updated_nexus_structure.updated_at == timezone.now()
            assert updated_nexus_structure.updated_at != nexus_structure.updated_at

    def test_sync_structures_old_instances(self):
        with freeze_time() as frozen_time:
            structure = CompanyFactory()
            assert sync_structures([build_structure(serialize_structure(structure), Service.EMPLOIS)]) == 1
            assert NexusStructure.objects.get().updated_at == timezone.now()

            frozen_time.tick()
            NexusRessourceSyncStatusFactory(service=Service.EMPLOIS)
            assert NexusStructure.objects.exists() is False
            assert sync_structures([build_structure(serialize_structure(structure), Service.EMPLOIS)]) == 1
            assert NexusStructure.objects.get().updated_at == timezone.now()


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
