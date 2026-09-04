import datetime
import random
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertRedirects

from itou.users.enums import ActionKind, AssignmentEndReason
from itou.users.models import JobSeekerAssignment
from itou.www.job_seekers_views.forms import JobSeekerAssignmentForm
from tests.companies.factories import CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestCreateOrEditAssignment:
    def test_forbidden_access(self, client):
        job_seeker = JobSeekerFactory()
        assignment = JobSeekerAssignmentFactory(job_seeker=job_seeker)
        create_url = reverse("job_seekers_views:create_assignment", kwargs={"public_id": job_seeker.public_id})
        edit_url = reverse(
            "job_seekers_views:edit_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        for user in [job_seeker, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(create_url)
            assert response.status_code == 403
            response = client.post(edit_url)
            assert response.status_code == 403

    def test_permission_to_edit(self, client):
        user = PrescriberFactory(membership=True)
        assignment = JobSeekerAssignmentFactory()
        url = reverse(
            "job_seekers_views:edit_assignment",
            kwargs={"public_id": assignment.job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        client.force_login(user)

        response = client.get(url)
        assert response.status_code == 404

        assignment.professional = user
        assignment.save()
        response = client.get(url)
        assert response.status_code == 200

        assignment.prescriber_organization = PrescriberOrganizationFactory()
        assignment.save()
        response = client.get(url)
        assert response.status_code == 403

    def test_create_view(self, client):
        job_seeker = JobSeekerFactory()
        professional = PrescriberFactory(membership=True)
        url = reverse("job_seekers_views:create_assignment", kwargs={"public_id": job_seeker.public_id})

        client.force_login(professional)

        # The professional sets a reason
        post_data = {
            "reason": "iae",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment = JobSeekerAssignment.objects.get()
        assert assignment.reason == "iae"
        assert assignment.last_action_kind == ActionKind.SELF_ASSIGN
        assignment.delete()

        # Ensure other parameters are not taken into account
        post_data = {
            "reason": "iae",
            "ended_at": timezone.now(),
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment = JobSeekerAssignment.objects.get()
        assert assignment.reason == "iae"
        assert assignment.ended_at is None

        # Trying to create an assignment when one already exists redirects the user to the edit view
        response = client.get(url)
        back_url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})
        redirect_url = reverse(
            "job_seekers_views:edit_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
            query={"back_url": back_url},
        )
        assertRedirects(response, redirect_url)

    def test_edit_view(self, client, snapshot):
        job_seeker = JobSeekerFactory(for_snapshot=True)
        organization = PrescriberOrganizationFactory(for_snapshot=True)
        professional = PrescriberFactory(membership=True, membership__organization=organization)
        assignment = JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=professional,
            prescriber_organization=organization,
            created_at=datetime.datetime(2024, 6, 21, 0, 0, 0, tzinfo=datetime.UTC),
            updated_at=datetime.datetime(2024, 6, 24, 0, 0, 0, tzinfo=datetime.UTC),
        )
        url = reverse(
            "job_seekers_views:edit_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        client.force_login(professional)
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                (
                    "href",
                    f"%2Fjob-seekers%2F{job_seeker.public_id}%2Fassignments%2F{assignment.pk}%2Fedit",
                    f"%2Fjob-seekers%2F{job_seeker.public_id}%2Fassignments%2F[PK of Assignment]%2Fedit",
                ),
            ],
        )
        assert pretty_indented(html_details) == snapshot

        # The user clicks on "Accompagnement terminé"
        post_data = {
            "is_ongoing": "False",
            "reason": "",
        }
        now = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=now):
            response = client.post(url, data=post_data)

        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment.refresh_from_db()
        assert assignment.ended_at == now
        assert assignment.end_reason == AssignmentEndReason.MANUAL

        # If the assignment was archived, saving without changing anything won't change the ending date or end reason
        assignment.end_reason = AssignmentEndReason.AUTOMATIC
        assignment.save()
        post_data = {
            "is_ongoing": "False",
            "reason": "",
        }
        now = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=now):
            response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment_updated = JobSeekerAssignment.objects.get(pk=assignment.pk)
        assert assignment.ended_at == assignment_updated.ended_at
        assert assignment.end_reason == AssignmentEndReason.AUTOMATIC

        # Cannot make an assignment active again if there's an ongoing assignment already
        active_assignment = JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=professional,
            prescriber_organization=organization,
        )
        post_data = {
            "is_ongoing": "True",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assert not assignment.is_active
        active_assignment.delete()

        # The professional follows again the job seeker
        post_data = {
            "is_ongoing": "True",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment.refresh_from_db()
        assert assignment.is_active

        # The professional sets a reason
        post_data = {
            "is_ongoing": "True",
            "reason": "iae",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))

        assignment = JobSeekerAssignment.objects.get()
        assert assignment.reason == "iae"

        # Make sure an assignment is no longer assigned to an unknown advisor after edition
        assignment.assigned_to_unknown_advisor = True
        assignment.save()
        post_data = {
            "is_ongoing": "True",
            "reason": "iae",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("job_seekers_views:advisors", kwargs={"public_id": job_seeker.public_id}))
        assignment.refresh_from_db()
        assert assignment.assigned_to_unknown_advisor is False

    def test_form(self):
        job_seeker = JobSeekerFactory()
        professional = PrescriberFactory()

        # Creation form
        assignment = JobSeekerAssignment(job_seeker=job_seeker, professional=professional)
        form = JobSeekerAssignmentForm(instance=assignment, active_assignment=None)
        assert form.fields.get("is_ongoing") is None

        # Edition form
        assignment = JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=professional)
        form = JobSeekerAssignmentForm(instance=assignment, active_assignment=assignment)
        assert form.fields.get("is_ongoing") is not None

        # Check the is_ongoing field is disabled if an active assignment
        # exists and we try to make an archived assignment active again
        archived_assignment = JobSeekerAssignmentFactory(
            job_seeker=job_seeker,
            professional=professional,
            ended_at=timezone.now(),
            end_reason=AssignmentEndReason.AUTOMATIC,
        )
        form = JobSeekerAssignmentForm(instance=archived_assignment, active_assignment=assignment)
        assert form.fields.get("is_ongoing") is not None
        assert form.fields.get("is_ongoing").disabled


class TestArchiveAssignment:
    def test_forbidden_access(self, client):
        assignment = JobSeekerAssignmentFactory()
        job_seeker = assignment.job_seeker
        url = reverse(
            "job_seekers_views:archive_assignment",
            kwargs={"public_id": job_seeker.public_id, "assignment_pk": assignment.pk},
        )

        for user in [job_seeker, LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            response = client.post(url)
            assert response.status_code == 403

    def test_permission(self, client):
        user = PrescriberFactory(membership=True)
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
        membership = random.choice([PrescriberMembershipFactory, CompanyMembershipFactory])()
        prescriber_organization = getattr(membership, "organization", None)
        company = getattr(membership, "company", None)
        user = membership.user
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
