import datetime

import pytest
from django.contrib.auth import get_user
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.utils.urls import add_url_params
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


def test_job_seeker_admin_link(admin_client):
    job_seeker = JobSeekerFactory()

    response = admin_client.get(reverse("admin:users_user_change", args=(job_seeker.pk,)))
    assertContains(response, "Pas de groupe de suivi")

    group = FollowUpGroupFactory(beneficiary=job_seeker, memberships=2)
    response = admin_client.get(reverse("admin:users_user_change", args=(job_seeker.pk,)))
    expected_url = reverse("admin:gps_followupgroup_change", args=(group.pk,))
    assertContains(response, "Groupe de suivi de ce bénéficiaire")

    # Assert that the lookup works
    admin_client.get(expected_url)


@pytest.mark.parametrize("user_factory", [EmployerFactory, PrescriberFactory])
def test_participant_admin_link(admin_client, user_factory):
    participant = user_factory()

    response = admin_client.get(reverse("admin:users_user_change", args=(participant.pk,)))
    expected_url = add_url_params(reverse("admin:gps_followupgroupmembership_changelist"), {"member": participant.pk})
    assertContains(response, expected_url)
    assertContains(response, "Liste des relations de cet utilisateur (0)")

    FollowUpGroupMembershipFactory.create_batch(2, member=participant)
    response = admin_client.get(reverse("admin:users_user_change", args=(participant.pk,)))
    assertContains(response, "Liste des relations de cet utilisateur (2)")

    # Assert that the lookup works
    admin_client.get(expected_url)


def test_create_follow_up_membership(admin_client):
    group = FollowUpGroupFactory()
    prescriber = PrescriberFactory()

    url = reverse("admin:gps_followupgroupmembership_add")

    post_data = {
        "is_active": "on",
        "follow_up_group": group.pk,
        "member": prescriber.pk,
        "created_at_0": "01/01/2025",
        "created_at_1": "12:34:56",
        "last_contact_at_0": "01/01/2025",
        "last_contact_at_1": "12:34:57",
        "started_at": "01/01/2025",
        "ended_at": "",
    }
    response = admin_client.post(url, data=post_data)
    assert response.status_code == 302

    membership = group.memberships.get()
    assert membership.creator == get_user(admin_client)
    assert membership.ended_at is None
    # the admin is in UTC+1
    assert membership.created_at == datetime.datetime(2025, 1, 1, 11, 34, 56, tzinfo=datetime.UTC)
    assert membership.last_contact_at == datetime.datetime(2025, 1, 1, 11, 34, 57, tzinfo=datetime.UTC)
    assert membership.started_at == datetime.date(2025, 1, 1)

    # A second membership with the same member and follow_up_group won't work
    response = admin_client.post(url, data=post_data)
    assertContains(
        response, "Un objet Relation avec ces champs Groupe de suivi et Membre du groupe de suivi existe déjà."
    )


def test_reason_status_filter(admin_client):
    group = FollowUpGroupFactory()
    membership_with_reason = FollowUpGroupMembershipFactory(
        follow_up_group=group,
        reason="This is a reason",
    )
    membership_without_reason = FollowUpGroupMembershipFactory(
        follow_up_group=group,
        reason="",
    )

    membership_admin_url = reverse("admin:gps_followupgroupmembership_changelist")

    response = admin_client.get(membership_admin_url + "?has_reason=yes")
    assertContains(response, membership_with_reason.member.email)
    assertNotContains(response, membership_without_reason.member.email)

    response = admin_client.get(membership_admin_url + "?has_reason=no")
    assertContains(response, membership_without_reason.member.email)
    assertNotContains(response, membership_with_reason.member.email)
