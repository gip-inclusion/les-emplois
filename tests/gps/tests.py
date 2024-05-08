import pytest
from django.test.utils import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from tests.gps.factories import FollowUpGroupFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


def test_user_autocomplete():
    member = PrescriberFactory(first_name="gps member first_name")
    beneficiary = JobSeekerFactory(first_name="gps beneficiary first_name")
    another_beneficiary = JobSeekerFactory(first_name="gps another beneficiary first_name")

    FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    FollowUpGroupFactory(beneficiary=another_beneficiary, memberships=2)

    # Default to kind=UserKind.JOB_SEEKER
    assert User.objects.autocomplete("gps").count() == 2
    assert User.objects.autocomplete("gps member").count() == 0
    assert User.objects.autocomplete("gps member", kind=UserKind.PRESCRIBER).count() == 1

    # We should not get ourself nor the other user because we are a member of his group
    users = User.objects.autocomplete("gps", current_user=member)
    assert users.count() == 1
    assert users[0].id == another_beneficiary.id


@pytest.mark.parametrize(
    "is_referent",
    [
        True,
        False,
    ],
)
def test_join_group_as_job_seeker(is_referent, client, snapshot):
    prescriber = PrescriberFactory()
    job_seeker = JobSeekerFactory()

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    assert str(parse_response_to_soup(response, "#join_group")) == snapshot

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
    other_prescriber = PrescriberFactory()

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


def test_join_group_as_prescriber(client):
    prescriber = PrescriberFactory()
    another_prescriber = PrescriberFactory()

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    post_data = {
        "user": another_prescriber.id,
        "is_referent": True,
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 200

    assertContains(response, "Seul un candidat peut être ajouté à un groupe de suivi")


def test_navigation(snapshot, client):
    member = PrescriberFactory(first_name="gps member first_name")
    member_first_beneficiary = JobSeekerFactory(first_name="gps first beneficiary first_name")
    member_second_beneficiary = JobSeekerFactory(first_name="gps second beneficiary first_name")

    FollowUpGroupFactory(beneficiary=member_first_beneficiary, memberships=4, memberships__member=member)
    FollowUpGroupFactory(beneficiary=member_second_beneficiary, memberships=2, memberships__member=member)

    client.force_login(member)

    response = client.get(reverse("dashboard:index"))

    assert str(parse_response_to_soup(response, "#gps-card")) == snapshot

    response = client.get(reverse("gps:my_groups"))

    assertContains(response, member_first_beneficiary.get_full_name())
    assertContains(response, member_second_beneficiary.get_full_name())

    assertContains(response, member_first_beneficiary.email)
    assertContains(response, member_second_beneficiary.email)

    assertContains(response, "référent")

    assertContains(response, "2 bénéficiaires suivis")


def test_access_as_jobseeker(client):
    user = JobSeekerFactory()
    client.force_login(user)

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 302

    response = client.get(reverse("gps:join_group"))
    assert response.status_code == 302


@override_settings(GPS_ENABLED=True)
def test_access_gps_enabled(client, snapshot):
    user = PrescriberFactory()
    client.force_login(user)

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 200

    response = client.get(reverse("gps:join_group"))
    assert response.status_code == 200

    response = client.get(reverse("dashboard:index"))
    assert str(parse_response_to_soup(response, "#gps-card")) == snapshot

    user = JobSeekerFactory()
    client.force_login(user)
    response = client.get(reverse("dashboard:index"))
    assertNotContains(response, "gps-card")


@override_settings(GPS_ENABLED=False)
def test_access_gps_disabled(client):
    user = PrescriberFactory()
    client.force_login(user)

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 403

    response = client.get(reverse("gps:join_group"))
    assert response.status_code == 403

    response = client.get(reverse("dashboard:index"))
    assertNotContains(response, "gps-card")


def test_leave_group(client):

    member = PrescriberFactory()
    another_member = PrescriberFactory()

    beneficiary = JobSeekerFactory()
    another_beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    another_group = FollowUpGroupFactory(
        beneficiary=another_beneficiary, memberships=2, memberships__member=another_member
    )

    assert my_group.members.count() == 4

    client.force_login(member)
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302
    assert my_group.members.count() == 3

    # We can't leave a group we're not part of
    assert another_group.members.count() == 2
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": another_group.id}))
    assert response.status_code == 302
    assert another_group.members.count() == 2


def test_referent_group(client):

    prescriber = PrescriberFactory()

    beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=prescriber)

    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()

    assert membership.is_referent

    client.force_login(prescriber)
    response = client.get(reverse("gps:toggle_referent", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    membership.refresh_from_db()

    assert not membership.is_referent
