import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.www.gps.enums import EndReason
from tests.companies.factories import CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


def test_bulk_created():
    FollowUpGroupFactory.create_batch(2, memberships=2)  # 4 memberships
    FollowUpGroupFactory.create_batch(3, created_in_bulk=True, memberships=2)  # 6 memberships
    assert FollowUpGroup.objects.not_bulk_created().count() == 2
    assert FollowUpGroup.objects.bulk_created().count() == 3

    assert FollowUpGroupMembership.objects.not_bulk_created().count() == 4
    assert FollowUpGroupMembership.objects.bulk_created().count() == 6


class TestFollowBeneficiary:
    def test_dates(self):
        beneficiary = JobSeekerFactory()
        prescriber = PrescriberFactory()

        with freeze_time() as frozen_time:
            created_at = timezone.now()
            started_at = timezone.localdate()
            _, created = FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
            assert created is True
            group = FollowUpGroup.objects.get()
            membership = group.memberships.get()
            assert membership.created_at == created_at
            assert membership.started_at == started_at
            assert membership.ended_at is None
            assert membership.end_reason is None
            assert membership.last_contact_at == created_at
            assert membership.creator == prescriber

            membership.ended_at = started_at
            membership.end_reason = EndReason.MANUAL
            membership.save()
            frozen_time.tick()
            updated_at = timezone.now()

            _, created = FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
            assert created is False
            membership.refresh_from_db()
            assert membership.created_at == created_at
            assert membership.started_at == started_at
            assert membership.ended_at is None
            assert membership.end_reason is None
            assert membership.last_contact_at == updated_at

    def test_non_prescriber_or_employer(self):
        staff = ItouStaffFactory()
        beneficiary = JobSeekerFactory()
        FollowUpGroup.objects.follow_beneficiary(beneficiary, staff)
        assert not FollowUpGroup.objects.exists()

    def test_is_active(self):
        beneficiary = JobSeekerFactory()
        prescriber = PrescriberFactory()

        # New follower uses kwarg value
        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
        group = FollowUpGroup.objects.get()
        membership = group.memberships.get()
        assert membership.is_active is True

        membership.is_active = False
        membership.save()

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
        membership.refresh_from_db()
        assert membership.is_active is True

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber, is_active=False)
        membership.refresh_from_db()
        assert membership.is_active is False

    @pytest.mark.parametrize("factory", [PrescriberFactory, EmployerFactory, LaborInspectorFactory, ItouStaffFactory])
    def test_is_job_seeker(self, factory):
        not_a_beneficiary = factory()
        prescriber = PrescriberFactory()

        with pytest.raises(AssertionError):
            FollowUpGroup.objects.follow_beneficiary(not_a_beneficiary, prescriber)


@pytest.mark.parametrize(
    "UserFactory,MembershipFactory,relation_name",
    [
        (EmployerFactory, CompanyMembershipFactory, "company"),
        (PrescriberFactory, PrescriberMembershipFactory, "organization"),
    ],
)
def test_manager_organizations_names(UserFactory, MembershipFactory, relation_name):
    user = UserFactory()
    first_membership = MembershipFactory(is_admin=False, user=user)
    admin_membership = MembershipFactory(is_admin=True, user=user)
    last_membership = MembershipFactory(is_admin=False, user=user)
    FollowUpGroupFactory(memberships=True, memberships__member=user)
    with assertNumQueries(1):
        group_membership = FollowUpGroupMembership.objects.with_members_organizations_names().get(member_id=user.pk)

    # The organization we are admin of should come first
    assert group_membership.organization_name == getattr(admin_membership, relation_name).name
    admin_membership.delete()

    group_membership = FollowUpGroupMembership.objects.with_members_organizations_names().get(member_id=user.pk)
    # Then it's ordered by membership creation date.
    assert group_membership.organization_name == getattr(first_membership, relation_name).name

    # No membership
    first_membership.delete()
    last_membership.delete()

    group_membership = FollowUpGroupMembership.objects.with_members_organizations_names().get(member_id=user.pk)
    assert not group_membership.organization_name


@freeze_time("2025-02-13T16:44:42")
def test_human_readable_followed_for():
    membership = FollowUpGroupMembershipFactory()

    membership.started_at = datetime.date(2025, 2, 1)
    assert membership.human_readable_followed_for == "moins d’un mois"

    membership.started_at = datetime.date(2025, 1, 14)
    assert membership.human_readable_followed_for == "moins d’un mois"

    membership.started_at = datetime.date(2025, 1, 13)
    assert membership.human_readable_followed_for == "1 mois"

    membership.started_at = datetime.date(2024, 2, 14)
    assert membership.human_readable_followed_for == "11 mois"

    membership.started_at = datetime.date(2024, 2, 13)
    assert membership.human_readable_followed_for == "1 an"

    membership.started_at = datetime.date(2024, 1, 13)
    assert membership.human_readable_followed_for == "1 an, 1 mois"
