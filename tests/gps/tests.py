import datetime

import freezegun
import pytest
from bs4 import BeautifulSoup
from django.conf import settings
from django.test.utils import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNumQueries

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from tests.companies.factories import CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)
from tests.utils.test import TestCase, parse_response_to_soup


# To be able to use assertCountEqual
class GpsTest(TestCase):
    def test_user_autocomplete(self):
        prescriber = PrescriberFactory(first_name="gps member Vince")
        first_beneficiary = JobSeekerFactory(first_name="gps beneficiary Bob", last_name="Le Brico")
        second_beneficiary = JobSeekerFactory(first_name="gps second beneficiary Martin", last_name="Pêcheur")
        third_beneficiary = JobSeekerFactory(first_name="gps third beneficiary Foo", last_name="Bar")

        my_group = FollowUpGroupFactory(beneficiary=first_beneficiary, memberships=4, memberships__member=prescriber)
        FollowUpGroupFactory(beneficiary=third_beneficiary, memberships=3, memberships__member=prescriber)
        FollowUpGroupFactory(beneficiary=second_beneficiary, memberships=2)

        # Default to kind=UserKind.JOB_SEEKER
        # We should get the 3 job seekers
        users = User.objects.autocomplete("gps")
        self.assertCountEqual(users, [first_beneficiary, second_beneficiary, third_beneficiary])

        # We should not get the prescriber by default
        assert User.objects.autocomplete("gps member").count() == 0

        # Only when we specify his kind
        assert User.objects.autocomplete("gps member", kind=UserKind.PRESCRIBER).count() == 1

        # We should not get ourself nor the first and third user user because we are a member of their group
        users = User.objects.autocomplete("gps", current_user=prescriber).all()
        self.assertCountEqual(users, [second_beneficiary])

        # Now, if we remove the first user from our group by setting the membership to is_active False
        # The autocomplete should return it again
        membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()
        membership.is_active = False
        membership.save()

        # We should not get ourself but we should get the first beneficiary (we are is_active=False)
        # and the second one (we are not part of his group)
        users = User.objects.autocomplete("gps", current_user=prescriber)

        self.assertCountEqual(users, [first_beneficiary, second_beneficiary])


@pytest.mark.parametrize(
    "is_referent",
    [
        True,
        False,
    ],
)
def test_join_group_of_a_job_seeker(is_referent, client, snapshot):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory()

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    post_data = {
        "user": job_seeker.id,
        "is_referent": is_referent,
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 302

    # A follow up group and a membership to this group should have been created
    assert FollowUpGroup.objects.count() == 1
    follow_up_group = FollowUpGroup.objects.get(beneficiary=job_seeker)
    assert FollowUpGroupMembership.objects.count() == 1
    membership = (
        FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=follow_up_group).first()
    )

    assert membership.is_referent == is_referent

    # Login with another prescriber and join the same follow_up_group
    other_prescriber = PrescriberFactory(membership=True)

    client.force_login(other_prescriber)

    post_data = {
        "user": job_seeker.id,
        "is_referent": not is_referent,
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 302

    # We should not have created another FollowUpGroup
    assert FollowUpGroup.objects.count() == 1
    follow_up_group = FollowUpGroup.objects.get(beneficiary=job_seeker)

    # Just a new membership should have been created
    assert FollowUpGroupMembership.objects.count() == 2


def test_join_group_of_a_prescriber(client):
    prescriber = PrescriberFactory(membership=True)
    another_prescriber = PrescriberFactory(membership=True)

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    post_data = {
        "user": another_prescriber.id,
        "is_referent": True,
    }

    response = client.post(url, data=post_data)

    # We should not be redirected to "my_groups" because the form is not valid
    # regarding queryset=User.objects.filter(kind=UserKind.JOB_SEEKER)
    assert response.status_code == 200
    assertContains(
        response,
        "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
    )


@override_settings(TALLY_URL="https://hello-tally.so")
def test_dashboard_card(snapshot, client):
    member = PrescriberFactory(for_snapshot=True)
    client.force_login(member)
    response = client.get(reverse("dashboard:index"))
    assert str(parse_response_to_soup(response, "#gps-card")) == snapshot


@freezegun.freeze_time("2024-06-22", tick=True)
def test_my_groups(snapshot, client):
    user = PrescriberFactory()
    client.force_login(user)

    # Was created in bulk.
    group = FollowUpGroupFactory(
        memberships=1,
        beneficiary__first_name="Paco",
        beneficiary__last_name="de Lucia",
        created_in_bulk=True,
    )
    FollowUpGroup.objects.follow_beneficiary(beneficiary=group.beneficiary, user=user, is_referent=True)
    membership = group.memberships.get(member=user)
    membership.created_at = datetime.datetime.combine(
        settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(), tzinfo=datetime.UTC
    )
    membership.save()

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 200
    groups = parse_response_to_soup(response, selector="#follow-up-groups-section").select(".membership-card")
    assert len(groups) == 1
    assert "Vous avez ajouté ce bénéficiaire le" not in str(groups[0])

    # Nominal case
    # Groups created latelly should come first.
    group = FollowUpGroupFactory(pk=34, memberships=1, for_snapshot=True)
    FollowUpGroup.objects.follow_beneficiary(beneficiary=group.beneficiary, user=user)

    response = client.get(reverse("gps:my_groups"))
    groups = parse_response_to_soup(response, selector="#follow-up-groups-section").select(".membership-card")
    assert len(groups) == 2
    assert str(groups[0]) == snapshot(name="test_my_groups__group_card")

    # Test `is_referent` display.
    group = FollowUpGroupFactory(memberships=1, beneficiary__first_name="Janis", beneficiary__last_name="Joplin")
    FollowUpGroup.objects.follow_beneficiary(beneficiary=group.beneficiary, user=user, is_referent=True)
    response = client.get(reverse("gps:my_groups"))
    groups = parse_response_to_soup(response, selector="#follow-up-groups-section").select(".membership-card")
    assert len(groups) == 3
    assert "Janis" in str(groups[0])
    assert "et êtes <strong>référent</strong>" in str(groups[0])


def test_access_as_jobseeker(client):
    user = JobSeekerWithAddressFactory()
    client.force_login(user)

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 302

    response = client.get(reverse("gps:join_group"))
    assert response.status_code == 302


def test_leave_group(client):
    member = PrescriberFactory(membership=True)
    another_member = PrescriberFactory(membership=True)

    beneficiary = JobSeekerFactory()
    another_beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    another_group = FollowUpGroupFactory(
        beneficiary=another_beneficiary,
        memberships=2,
        memberships__member=another_member,
    )

    # We have 4 group members
    assert my_group.members.count() == 4

    # And the 4 are active
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=my_group).count() == 4

    client.force_login(member)
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    # We still have 4 group members
    assert my_group.members.count() == 4
    # But only 3 are active
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=my_group).count() == 3

    # We can't leave a group we're not part of
    assert another_group.members.count() == 2
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": another_group.id}))
    assert response.status_code == 302
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=another_group).count() == 2


def test_referent_group(client):
    prescriber = PrescriberFactory(membership=True)

    beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=prescriber)

    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()

    assert membership.is_referent

    client.force_login(prescriber)
    response = client.get(reverse("gps:toggle_referent", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    membership.refresh_from_db()

    assert not membership.is_referent


@freezegun.freeze_time("2024-06-21")
def test_beneficiary_details(client, snapshot):
    prescriber = PrescriberFactory(membership=True, for_snapshot=True, membership__organization__name="Les Olivades")
    beneficiary = JobSeekerFactory(for_snapshot=True)
    FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)

    client.force_login(prescriber)

    user_details_url = reverse("users:details", kwargs={"public_id": beneficiary.public_id})
    response = client.get(user_details_url)
    html_details = parse_response_to_soup(response, selector="#beneficiary_details_container")
    assert str(html_details) == snapshot
    user_dropdown_menu = parse_response_to_soup(response, selector="div#dashboardUserDropdown")

    assert prescriber.email in str(user_dropdown_menu)
    assert beneficiary.email not in str(user_dropdown_menu)


def test_remove_members_from_group(client):
    prescriber = PrescriberFactory(membership=True)

    beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=prescriber)

    client.force_login(prescriber)

    user_details_url = reverse("users:details", kwargs={"public_id": beneficiary.public_id})
    my_groups_url = reverse("gps:my_groups")

    response = client.get(my_groups_url)
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")

    # Prescriber has only one group
    assert len(soup.select("div.c-box--results__header")) == 1

    response = client.get(user_details_url)
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")

    # The group of this beneficiary contains 4 members
    assert len(soup.select("div.gps_intervenant")) == 4

    # Setting is_active False to the prescriber membership should remove it from the group
    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()
    membership.is_active = False
    membership.save()

    response = client.get(my_groups_url)
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")

    # Prescriber doesn't have group anymore
    assert len(soup.select("div.c-box--results__header")) == 0

    response = client.get(user_details_url)
    soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")
    assert len(soup.select("div.gps_intervenant")) == 3


##############################################################
######################### MODELS #############################
##############################################################
# TODO(cms): split tests into a new file.
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
