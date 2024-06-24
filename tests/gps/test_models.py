import datetime

import pytest
from django.conf import settings
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


def test_membership_is_from_bulk_creation():
    membership = FollowUpGroupMembershipFactory()
    assert not membership.is_from_bulk_creation

    membership.created_at = datetime.datetime.combine(
        settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(), tzinfo=datetime.UTC
    )
    assert membership.is_from_bulk_creation


def test_follow_beneficiary():
    beneficiary = JobSeekerFactory()
    prescriber = PrescriberFactory(membership=True)

    FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=prescriber, is_referent=True)
    group = FollowUpGroup.objects.get()
    membership = group.memberships.get()
    assert membership.is_active is True
    assert membership.is_referent is True
    assert membership.creator == prescriber

    membership.is_active = False
    membership.is_referent = False
    membership.save()

    FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=prescriber, is_referent=True)
    group = FollowUpGroup.objects.get()
    membership = group.memberships.get()
    assert membership.is_active is True
    assert membership.is_referent is True

    membership.is_active = False
    membership.save()

    FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=prescriber, is_referent=False)
    group = FollowUpGroup.objects.get()
    membership = group.memberships.get()
    assert membership.is_active is True
    assert membership.is_referent is False

    other_member = EmployerFactory()
    FollowUpGroup.objects.follow_beneficiary(beneficiary=beneficiary, user=other_member, is_referent=True)
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
