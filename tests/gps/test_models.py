import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.www.gps.enums import EndReason
from tests.companies.factories import CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerAssignmentFactory,
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

    def test_referent(self):
        job_seeker = JobSeekerFactory()
        prescriber_1 = PrescriberFactory()
        follow_up_group = FollowUpGroupFactory(beneficiary=job_seeker)
        FollowUpGroupMembershipFactory(member=prescriber_1, follow_up_group=follow_up_group)

        # No advisor
        assert follow_up_group.referent is None

        # Last known advisor
        prescriber_2 = PrescriberFactory()
        membership_2 = FollowUpGroupMembershipFactory(
            member=prescriber_2,
            follow_up_group=follow_up_group,
        )
        JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=prescriber_2)

        follow_up_group.refresh_from_db()
        assert follow_up_group.referent == membership_2

        # Last known advisor is not referenced
        organization = PrescriberOrganizationFactory(with_membership=True)
        prescriber_3 = organization.members.first()
        FollowUpGroupMembershipFactory(
            member=prescriber_3,
            follow_up_group=follow_up_group,
        )
        JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=prescriber_2,
            prescriber_organization=organization,
            assigned_to_unknown_advisor=True,
        )

        follow_up_group.refresh_from_db()
        assert follow_up_group.referent is None

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
    def test_is_job_seeker(self, factory, caplog):
        not_a_beneficiary = factory()
        prescriber = PrescriberFactory()
        FollowUpGroup.objects.follow_beneficiary(not_a_beneficiary, prescriber)

        assert not FollowUpGroup.objects.exists()
        assert f"We should not try to add a FollowUpGroup on beneficiary={not_a_beneficiary}" in caplog.messages

    def test_inactive_beneficiary(self, caplog):
        beneficiary = JobSeekerFactory(is_active=False)
        prescriber = PrescriberFactory()
        FollowUpGroup.objects.follow_beneficiary(beneficiary, prescriber)

        assert not FollowUpGroup.objects.exists()
        assert f"Cannot follow inactive beneficiary={beneficiary}" in caplog.messages

    @pytest.mark.parametrize("factory", [PrescriberFactory, EmployerFactory])
    def test_inactive_prescriber_or_employer(self, factory, caplog):
        beneficiary = JobSeekerFactory()
        user = factory(is_active=False)
        FollowUpGroup.objects.follow_beneficiary(beneficiary, user)

        assert not FollowUpGroup.objects.exists()
        assert f"Cannot follow beneficiary with inactive user={user}" in caplog.messages


class TestFollowUpGroupMembership:
    def test_organization_name_with_company_membership(self):
        # Inactive membership => None
        company_mship = CompanyMembershipFactory(is_active=False)
        group = FollowUpGroupMembershipFactory(member=company_mship.user)
        assert group.organization_name is None

        # Active membership => company name
        company_mship.is_active = True
        company_mship.save()
        assert group.organization_name == company_mship.company.display_name

    def test_organization_name_with_organization_membership(self):
        # Inactive membership => None
        prescriber_mship = PrescriberMembershipFactory(is_active=False)
        group = FollowUpGroupMembershipFactory(member=prescriber_mship.user)
        assert group.organization_name is None

        # Active membership => prescriber organization name
        prescriber_mship.is_active = True
        prescriber_mship.save()
        assert group.organization_name == prescriber_mship.organization.display_name


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


def test_follow_up_group_active_memberships():
    follow_up_group = FollowUpGroupFactory()
    membership_1 = FollowUpGroupMembershipFactory(follow_up_group=follow_up_group)
    membership_2 = FollowUpGroupMembershipFactory(follow_up_group=follow_up_group)

    assertQuerySetEqual(
        follow_up_group.memberships.all(),
        [membership_1, membership_2],
        ordered=False,
    )

    membership_2.member.is_active = False
    membership_2.member.save()

    assertQuerySetEqual(follow_up_group.memberships.all(), [membership_1])
