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


class TestAssignOneselfAsAdvisor:
    def test_view(self, client):
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

        assert job_seeker.last_assignment == assignment

        client.force_login(professional)

        response = client.post(
            reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": job_seeker.public_id})
        )
        assertRedirects(response, reverse("job_seekers_views:list"), fetch_redirect_response=False)
        del job_seeker.last_assignment
        last_assignment = job_seeker.last_assignment
        assert last_assignment.advisor == professional
        assert last_assignment.organization == organization
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
            partial(EmployerFactory, membership=True),
        ],
        ids=["prescriber", "employer"],
    )
    def test_invalid(self, client, professional_factory):
        # Needs to be logged in
        response = client.get(
            reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()})
        )
        assert response.status_code == 302

        professional = professional_factory()
        client.force_login(professional)

        # Needs to be a POST request
        response = client.get(
            reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()})
        )
        assert response.status_code == 405

        # Needs to be an existing jobseeker
        response = client.post(
            reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()})
        )
        assert response.status_code == 404
