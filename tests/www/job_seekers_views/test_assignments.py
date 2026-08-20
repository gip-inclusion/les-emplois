import random
import uuid

from django.contrib import messages
from django.urls import reverse
from pytest_django.asserts import assertMessages, assertRedirects

from itou.users.enums import ActionKind, AssignmentEndReason
from itou.users.models import JobSeekerAssignment
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


class TestAssignOneselfAsAdvisor:
    def test_view(self, client):
        professional = PrescriberFactory()
        organization = professional.prescriberorganization_set.get()
        job_seeker = JobSeekerFactory()
        assignment = JobSeekerAssignmentFactory(job_seeker=job_seeker)
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

    def test_invalid(self, client):
        # Needs to be logged in
        response = client.get(
            reverse("job_seekers_views:assign_oneself_as_advisor", kwargs={"public_id": uuid.uuid4()})
        )
        assert response.status_code == 302

        professional = random.choice((PrescriberFactory, EmployerFactory))()
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


class TestArchiveAssignment:
    def test_forbidden_access(self, client):
        assignment = JobSeekerAssignmentFactory()
        job_seeker = assignment.job_seeker
        url = reverse(
            "job_seekers_views:archive_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        for user in [job_seeker, LaborInspectorFactory()]:
            client.force_login(user)
            response = client.post(url)
            assert response.status_code == 403

    def test_permission(self, client):
        user = PrescriberFactory()
        assignment = JobSeekerAssignmentFactory()
        job_seeker = assignment.job_seeker
        url = reverse(
            "job_seekers_views:archive_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        client.force_login(user)

        response = client.post(url)
        assert response.status_code == 404
        assignment.refresh_from_db()
        assert assignment.is_active

        assignment.professional = user
        assignment.save()
        response = client.post(url)
        assert response.status_code == 302
        assignment.refresh_from_db()
        assert assignment.ended_at is not None
        assert assignment.end_reason == AssignmentEndReason.MANUAL

    def test_view(self, client):
        user = random.choice((PrescriberFactory, EmployerFactory))()
        prescriber_organization = user.prescriberorganization_set.first()
        company = user.company_set.first()
        job_seeker = JobSeekerFactory()
        advisors_tab_url = reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id})

        def archive_assignment_url(assignment_pk):
            return reverse(
                "job_seekers_views:archive_assignment",
                kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment_pk},
            )

        client.force_login(user)

        # Archive assignment without organization
        assignment = JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=user)
        response = client.post(archive_assignment_url(assignment.pk))
        assignment.refresh_from_db()
        assertRedirects(response, advisors_tab_url)
        assert assignment.ended_at is not None
        assert assignment.end_reason == AssignmentEndReason.MANUAL

        # Archive assignment with other organization
        assignment = JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=user,
            prescriber_organization=PrescriberOrganizationFactory(),
        )
        response = client.post(archive_assignment_url(assignment.pk))
        assignment.refresh_from_db()
        assert response.status_code == 403
        assert assignment.is_active

        # Archive assignment
        assignment = JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            company=company,
        )
        response = client.post(archive_assignment_url(assignment.pk))
        assignment.refresh_from_db()
        assertRedirects(response, advisors_tab_url)
        assert assignment.ended_at is not None
        assert assignment.end_reason == AssignmentEndReason.MANUAL

        # Archive ended assignment
        response = client.post(archive_assignment_url(assignment.pk))
        assertRedirects(response, advisors_tab_url)
        refreshed_assignment = JobSeekerAssignment.objects.get(pk=assignment.pk)
        assert assignment.ended_at == refreshed_assignment.ended_at
        assert assignment.end_reason == refreshed_assignment.end_reason
