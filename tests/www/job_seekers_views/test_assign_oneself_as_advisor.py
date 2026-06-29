import uuid
from functools import partial

import pytest
from django.contrib import messages
from django.urls import reverse
from pytest_django.asserts import assertMessages, assertRedirects

from itou.users.enums import ActionKind
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


def test_view(client):
    organization = PrescriberOrganizationFactory()
    professional = PrescriberFactory(membership__organization=organization)
    job_seeker = JobSeekerFactory()
    assignment = JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
    )
    SUCCESS_MESSAGE = messages.Message(
        messages.SUCCESS,
        "Accompagnateur mis à jour||"
        f"Vous êtes désormais le dernier accompagnateur connu de {job_seeker.get_inverted_full_name()}.",
        extra_tags="toast",
    )
    INFO_MESSAGE = messages.Message(
        messages.INFO,
        f"Vous êtes déjà le dernier accompagnateur connu de {job_seeker.get_inverted_full_name()}.",
        extra_tags="toast",
    )

    assert job_seeker.last_advisor_with_org == (assignment.professional, None)

    client.force_login(professional)

    response = client.post(
        reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": job_seeker.public_id})
    )
    assertRedirects(response, reverse("job_seekers_views:list"), fetch_redirect_response=False)
    del job_seeker.last_assignment
    last_assignment = job_seeker.last_assignment
    assert job_seeker.last_advisor_with_org == (professional, organization)
    assert last_assignment.last_action_kind == ActionKind.SELF_ASSIGN
    assertMessages(response, [SUCCESS_MESSAGE])

    response = client.post(
        reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": job_seeker.public_id})
    )
    assertRedirects(response, reverse("job_seekers_views:list"), fetch_redirect_response=False)
    del job_seeker.last_assignment
    assert job_seeker.last_assignment == last_assignment
    assertMessages(response, [SUCCESS_MESSAGE, INFO_MESSAGE])


@pytest.mark.parametrize(
    "professional_factory",
    [
        partial(PrescriberFactory, membership=True),
        partial(EmployerFactory, membership=True, membership__company__subject_to_iae_rules=True),
    ],
    ids=["prescriber", "iae_employer"],
)
def test_invalid(client, professional_factory):
    # Needs to be logged in
    response = client.get(reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 302

    professional = EmployerFactory(membership=True, membership__company__not_subject_to_iae_rules=True)
    client.force_login(professional)

    # Needs to be a POST request
    response = client.get(reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 405

    # Needs to be a prescriber or a IAE employer
    response = client.post(reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 403

    professional = professional_factory()
    client.force_login(professional)

    # Needs to be an existing jobseeker
    response = client.post(reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 404
