"""The list of the job seekers followed by a prescriber, within the "Prochaines étapes" experiment."""

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationRequestStatus
from tests.approvals.factories import ProlongationRequestFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


LIST_URL = reverse("job_seekers_views:list")
ORGANIZATION_LIST_URL = reverse("job_seekers_views:list_organization")
TABS = "s-tabs-01__nav"
SWITCH = 'id="job-seekers-structure-switch"'
BADGE = "Demande de prolongation"


@pytest.fixture(autouse=True)
def experiment_off(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = False
    settings.NEXT_STEPS_USER_PKS = []
    settings.NEXT_STEPS_COMPANY_PKS = []
    settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS = []


@pytest.fixture
def membership():
    return PrescriberMembershipFactory(organization__authorized=True)


@pytest.fixture
def coworker(membership):
    return PrescriberMembershipFactory(organization=membership.organization).user


def experiment_on(settings, membership):
    settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS = [membership.organization.pk]


def listed(response):
    return set(response.context["page_obj"].object_list)


def test_tabs_give_way_to_a_switch(client, settings, membership, coworker):
    client.force_login(membership.user)

    # Without the experiment: the tabs, no switch.
    response = client.get(LIST_URL)
    assertContains(response, TABS)
    assertNotContains(response, SWITCH)

    experiment_on(settings, membership)
    response = client.get(LIST_URL)
    assertNotContains(response, TABS)
    assertContains(response, SWITCH)
    # Off on the user's list, it leads to the structure's; on there, back.
    assertContains(response, f'action="{ORGANIZATION_LIST_URL}"')
    assertNotContains(response, "checked />")
    response = client.get(ORGANIZATION_LIST_URL)
    assertNotContains(response, TABS)
    assertContains(response, f'action="{LIST_URL}"')
    assertContains(response, "checked />")


def test_no_switch_alone_in_the_structure(client, settings, membership):
    experiment_on(settings, membership)
    client.force_login(membership.user)
    response = client.get(LIST_URL)
    assertNotContains(response, TABS)
    assertNotContains(response, SWITCH)


def test_job_seekers_with_a_pending_prolongation_request(client, settings, membership, coworker):
    organization = membership.organization
    followed = JobSeekerFactory()
    JobSeekerAssignmentFactory(job_seeker=followed, professional=membership.user, prescriber_organization=organization)
    # Pending, to the user: listed, though not followed.
    mine = ProlongationRequestFactory(prescriber_organization=organization, assigned_to=membership.user)
    # Pending, to a coworker: on the structure's list only.
    coworkers = ProlongationRequestFactory(prescriber_organization=organization, assigned_to=coworker)
    # Already decided, or to another organization: never.
    ProlongationRequestFactory(
        prescriber_organization=organization,
        assigned_to=membership.user,
        status=ProlongationRequestStatus.GRANTED,
        processed=True,
    )
    ProlongationRequestFactory()
    client.force_login(membership.user)

    # Without the experiment, the followed job seeker only.
    response = client.get(LIST_URL)
    assert listed(response) == {followed}
    assertNotContains(response, BADGE)

    experiment_on(settings, membership)
    response = client.get(LIST_URL)
    assert listed(response) == {followed, mine.approval.user}
    assertContains(response, BADGE, count=1)
    assertContains(response, reverse("approvals:prolongation_request_show", args=(mine.pk,)))
    # Never followed, so not archived.
    [row] = [job_seeker for job_seeker in listed(response) if job_seeker == mine.approval.user]
    assert row.archived is False

    response = client.get(ORGANIZATION_LIST_URL)
    assert listed(response) == {followed, mine.approval.user, coworkers.approval.user}
    assertContains(response, BADGE, count=2)

    # The archived job seekers are those once followed, no longer.
    response = client.get(LIST_URL, {"assignments": "archived"})
    assert listed(response) == set()

    # Through htmx, as when filtering.
    response = client.get(LIST_URL, headers={"HX-Request": "true"})
    assertContains(response, BADGE, count=1)


def test_not_for_unauthorized_prescribers(client, settings):
    membership = PrescriberMembershipFactory(organization__authorized=False)
    experiment_on(settings, membership)
    client.force_login(membership.user)
    response = client.get(LIST_URL)
    assert response.status_code == 200
    assertNotContains(response, BADGE)
