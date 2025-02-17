import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from tests.companies.factories import CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


def test_bulk_created():
    FollowUpGroupFactory.create_batch(2, memberships=2)  # 4 memberships
    FollowUpGroupFactory.create_batch(3, created_in_bulk=True, memberships=2)  # 6 memberships
    assert FollowUpGroup.objects.not_bulk_created().count() == 2
    assert FollowUpGroup.objects.bulk_created().count() == 3

    assert FollowUpGroupMembership.objects.not_bulk_created().count() == 4
    assert FollowUpGroupMembership.objects.bulk_created().count() == 6


def test_follow_beneficiary():
    beneficiary = JobSeekerFactory()
    prescriber = PrescriberFactory(membership=True)

    with freeze_time() as frozen_time:
        created_at = timezone.now()
        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber, is_referent=True)
        group = FollowUpGroup.objects.get()
        membership = group.memberships.get()
        assert membership.is_active is True
        assert membership.is_referent is True
        assert membership.created_at == created_at
        assert membership.started_at == created_at
        assert membership.last_contact_at == created_at
        assert membership.creator == prescriber

        membership.is_active = False
        membership.is_referent = False
        membership.save()
        frozen_time.tick()
        updated_at = timezone.now()

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber, is_referent=True)
        membership.refresh_from_db()
        assert membership.is_active is True
        assert membership.is_referent is True
        assert membership.created_at == created_at
        assert membership.started_at == created_at
        assert membership.last_contact_at == updated_at

        membership.is_active = False
        membership.save()

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber, is_referent=False)
        membership.refresh_from_db()
        assert membership.is_active is True
        assert membership.is_referent is False

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
        membership.refresh_from_db()
        assert membership.is_referent is False  # does not change

        membership.is_referent = True
        membership.save()

        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)
        membership.refresh_from_db()
        assert membership.is_referent is True  # does not change

        other_member = EmployerFactory()
        FollowUpGroup.objects.follow_beneficiary(beneficiary, other_member, is_referent=True)
        assert group.memberships.count() == 2
        other_membership = group.memberships.get(member=other_member)
        assert other_membership.is_referent is True  # No limit to the number of referent


@pytest.mark.parametrize(
    "UserFactory,MembershipFactory,relation_name",
    [
        (EmployerFactory, CompanyMembershipFactory, "company"),
        (PrescriberFactory, PrescriberMembershipFactory, "organization"),
    ],
)
def test_manager_organizations_names(UserFactory, MembershipFactory, relation_name):
    user = UserFactory()
    first_membership = MembershipFactory(is_active=True, is_admin=False, user=user)
    admin_membership = MembershipFactory(is_active=True, is_admin=True, user=user)
    last_membership = MembershipFactory(is_active=True, is_admin=False, user=user)
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

    membership.started_at = datetime.datetime(2025, 2, 1)
    assert membership.human_readable_followed_for == "moins d’un mois"

    membership.started_at = datetime.datetime(2025, 1, 14)
    assert membership.human_readable_followed_for == "moins d’un mois"

    membership.started_at = datetime.datetime(2025, 1, 13, 17, 0, 0)
    assert membership.human_readable_followed_for == "moins d’un mois"

    membership.started_at = datetime.datetime(2025, 1, 13, 16, 0, 0)
    assert membership.human_readable_followed_for == "1 mois"

    membership.started_at = datetime.datetime(2024, 2, 14)
    assert membership.human_readable_followed_for == "11 mois"

    membership.started_at = datetime.datetime(2024, 2, 13)
    assert membership.human_readable_followed_for == "1 an"

    membership.started_at = datetime.datetime(2024, 1, 13)
    assert membership.human_readable_followed_for == "1 an, 1 mois"
