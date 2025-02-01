import datetime

import pytest
from django.contrib.auth import get_user
from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.utils.urls import add_url_params
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


def test_job_seeker_admin_link(admin_client):
    job_seeker = JobSeekerFactory()

    response = admin_client.get(reverse("admin:users_user_change", args=(job_seeker.pk,)))
    expected_url = add_url_params(
        reverse("admin:gps_followupgroupmembership_changelist"), {"follow_up_group__beneficiary": job_seeker.pk}
    )
    assertContains(response, expected_url)
    assertContains(response, "Liste des professionnels suivant ce bénéficiaire (0)")

    FollowUpGroupFactory(beneficiary=job_seeker, memberships=2)
    response = admin_client.get(reverse("admin:users_user_change", args=(job_seeker.pk,)))
    assertContains(response, "Liste des professionnels suivant ce bénéficiaire (2)")

    # Assert that the lookup works
    admin_client.get(expected_url)


@pytest.mark.parametrize("user_factory", [EmployerFactory, PrescriberFactory])
def test_participant_admin_link(admin_client, user_factory):
    participant = user_factory()

    response = admin_client.get(reverse("admin:users_user_change", args=(participant.pk,)))
    expected_url = add_url_params(
        reverse("admin:gps_followupgroup_changelist"), {"memberships__member": participant.pk}
    )
    assertContains(response, expected_url)
    assertContains(response, "Liste des groupes de suivi de cet utilisateur (0)")

    FollowUpGroupMembershipFactory.create_batch(2, member=participant)
    response = admin_client.get(reverse("admin:users_user_change", args=(participant.pk,)))
    assertContains(response, "Liste des groupes de suivi de cet utilisateur (2)")

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
    }
    response = admin_client.post(url, data=post_data)
    assert response.status_code == 302

    membership = group.memberships.get()
    assert membership.creator == get_user(admin_client)
    assert membership.ended_at is None
    # the admin is in UTC+1
    assert membership.created_at == datetime.datetime(2025, 1, 1, 11, 34, 56, tzinfo=datetime.UTC)

    url = reverse("admin:gps_followupgroupmembership_change", args=(membership.pk,))
    response = admin_client.post(
        url,
        data={
            "created_at_0": "01/01/2025",
            "created_at_1": "12:34:56",
            # no is_active to set it to False
        },
    )
    assert response.status_code == 302

    membership.refresh_from_db()
    assert membership.ended_at is not None
