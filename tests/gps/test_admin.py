import pytest
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
