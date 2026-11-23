import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateUsed

from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog, JobApplicationWorkflow
from itou.users.enums import ActionKind
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


@pytest.fixture(autouse=True)
def experiment_for_everyone(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True


def advisor_url(assignment):
    return reverse(
        "next_steps_views:advisor",
        kwargs={"public_id": assignment.job_seeker.public_id, "assignment_pk": assignment.pk},
    )


def days_ago(days):
    return timezone.now() - datetime.timedelta(days=days)


def test_off_by_default_and_only_for_the_job_seeker(client, settings):
    membership = PrescriberMembershipFactory()
    assignment = JobSeekerAssignmentFactory()
    client.force_login(membership.user)

    settings.NEXT_STEPS_FOR_EVERYONE = False
    assert client.get(advisor_url(assignment)).status_code == 404
    settings.NEXT_STEPS_FOR_EVERYONE = True
    other_job_seeker_url = reverse(
        "next_steps_views:advisor",
        kwargs={"public_id": JobSeekerFactory().public_id, "assignment_pk": assignment.pk},
    )
    assert client.get(other_job_seeker_url).status_code == 404


def test_a_colleague_acts_for_the_job_seeker(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    organization = membership.organization
    colleague = PrescriberMembershipFactory(organization=organization).user
    job_seeker = JobSeekerFactory(created_by=colleague, date_joined=days_ago(30))
    application = JobApplicationFactory(
        job_seeker=job_seeker,
        sender=colleague,
        sent_by_prescriber=True,
        sender_prescriber_organization=organization,
        created_at=days_ago(2),
    )
    IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker, author=colleague, author_prescriber_organization=organization, created_at=days_ago(5)
    )
    # Sent for another organization: an act of another assignment.
    JobApplicationFactory(
        job_seeker=job_seeker,
        sender=colleague,
        sent_by_prescriber=True,
        sender_prescriber_organization=PrescriberOrganizationFactory(),
    )
    assignment = JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=colleague,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
        last_action_at=days_ago(2),
    )
    client.force_login(membership.user)

    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    assertTemplateUsed(response, "next_steps/advisor.html")
    assert [act.kind for act in response.context["acts"]] == [
        ActionKind.APPLY,
        ActionKind.IAE_ELIGIBILITY,
        ActionKind.CREATE,
    ]
    # The application is theirs to read.
    assertContains(response, reverse("apply:details_for_prescriber", kwargs={"job_application_id": application.pk}))
    assertContains(response, f"À {application.to_company.display_name}")
    assertContains(response, "Afficher l’adresse e-mail")


def test_an_employer_sees_no_more_than_on_the_job_seeker_page(client):
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    # A name of its own: a random one may match another name on the page.
    elsewhere = JobApplicationFactory(
        sent_by_authorized_prescriber=True, created_at=days_ago(3), to_company__name="Structure hors périmètre"
    )
    advisor = elsewhere.sender
    organization = elsewhere.sender_prescriber_organization
    job_seeker = elsewhere.job_seeker
    received = JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=company,
        sender=advisor,
        sent_by_prescriber=True,
        sender_prescriber_organization=organization,
        created_at=days_ago(1),
    )
    IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker, author=advisor, author_prescriber_organization=organization, created_at=days_ago(4)
    )
    assignment = JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=advisor,
        prescriber_organization=organization,
        last_action_kind=ActionKind.APPLY,
    )
    client.force_login(company.members.first())

    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    # The application to another company is out of their scope, as on the job seeker's applications tab.
    assert [act.kind for act in response.context["acts"]] == [ActionKind.APPLY, ActionKind.IAE_ELIGIBILITY]
    assertContains(response, reverse("apply:details_for_company", kwargs={"job_application_id": received.pk}))
    assertNotContains(response, elsewhere.to_company.display_name)


def test_an_employer_colleague_who_hired(client):
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    employer = company.members.first()
    colleague = CompanyMembershipFactory(company=company).user
    application = JobApplicationFactory(
        to_company=company, state=JobApplicationState.ACCEPTED, sent_by_authorized_prescriber=True
    )
    JobApplicationTransitionLog.objects.create(
        job_application=application,
        user=colleague,
        transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
        from_state=JobApplicationState.PROCESSING,
        to_state=JobApplicationState.ACCEPTED,
    )
    assignment = JobSeekerAssignmentFactory(
        job_seeker=application.job_seeker, professional=colleague, company=company, last_action_kind=ActionKind.ACCEPT
    )
    client.force_login(employer)

    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    [act] = response.context["acts"]
    assert (act.kind, act.detail) == (ActionKind.ACCEPT, f"Chez {company.display_name}")


def test_unknown_advisor_and_page_without_javascript(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    assignment = JobSeekerAssignmentFactory(
        professional=membership.user,
        prescriber_organization=membership.organization,
        assigned_to_unknown_advisor=True,
        last_action_kind=ActionKind.SELF_ASSIGN,
    )
    client.force_login(membership.user)

    response = client.get(advisor_url(assignment))
    assertTemplateUsed(response, "next_steps/advisor_page.html")
    # Their acts are not those of the professional who recorded the assignment: the last one only.
    assert [act.kind for act in response.context["acts"]] == [ActionKind.SELF_ASSIGN]
    assertContains(response, "Accompagnateur non renseigné")
    assertContains(response, "E-mail de la structure")


def test_job_seeker_page_opens_the_advisor_in_the_drawer(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    assignment = JobSeekerAssignmentFactory(
        professional=membership.user, prescriber_organization=membership.organization
    )
    client.force_login(membership.user)

    response = client.get(
        reverse("next_steps_views:job_seeker", kwargs={"public_id": assignment.job_seeker.public_id})
    )
    assertContains(response, f'hx-get="{advisor_url(assignment)}"')
    # Their own initials, filled.
    assertContains(response, "bg-tertiary text-white")


# One's own assignment
# ------------------------------------------------------------------------------


def edit_url(assignment):
    return reverse(
        "job_seekers_views:edit_assignment",
        kwargs={"public_id": assignment.job_seeker.public_id, "assignment_pk": assignment.pk},
    )


def end_url(assignment):
    return reverse(
        "next_steps_views:end_assignment",
        kwargs={"public_id": assignment.job_seeker.public_id, "assignment_pk": assignment.pk},
    )


def test_own_assignment_can_be_edited_and_ended(client):
    membership = PrescriberMembershipFactory()
    assignment = JobSeekerAssignmentFactory(
        professional=membership.user, prescriber_organization=membership.organization, reason=""
    )
    client.force_login(membership.user)

    # As on the existing advisors tab: edit it, precise its motif, end it.
    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    assertContains(response, "Modifier mon accompagnement")
    assertContains(response, "Préciser le motif de mon accompagnement")
    assertContains(response, f"{edit_url(assignment)}?back_url=")
    assertContains(response, f'hx-get="{end_url(assignment)}"')

    # Ending it is confirmed in the drawer, then posted to the existing view, back to the job seeker's page.
    response = client.get(end_url(assignment), HTTP_HX_REQUEST="true")
    assertContains(response, "cet usager n'apparaîtra plus dans votre liste d'accompagnements")
    archive_url = reverse(
        "job_seekers_views:archive_assignment",
        kwargs={"public_id": assignment.job_seeker.public_id, "assignment_pk": assignment.pk},
    )
    job_seeker_url = reverse("next_steps_views:job_seeker", kwargs={"public_id": assignment.job_seeker.public_id})
    assertContains(response, f'action="{archive_url}?back_url={job_seeker_url}"')
    response = client.post(f"{archive_url}?back_url={job_seeker_url}")
    assert response.url == job_seeker_url
    assignment.refresh_from_db()
    assert not assignment.is_active


def test_own_assignment_from_another_organization(client):
    membership = PrescriberMembershipFactory()
    other = PrescriberMembershipFactory(user=membership.user)
    assignment = JobSeekerAssignmentFactory(professional=membership.user, prescriber_organization=other.organization)
    client.force_login(membership.user)
    session = client.session
    session["current_organization"] = membership.organization.organization_switch_key
    session.save()

    # Managed from its organization: switch to it first.
    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    assertNotContains(response, "Modifier mon accompagnement")
    assertContains(response, f"Connectez-vous à la structure {other.organization.display_name}")
    assertContains(response, other.organization.organization_switch_key)
    assert client.get(end_url(assignment), HTTP_HX_REQUEST="true").status_code == 404


def test_someone_elses_assignment_has_no_actions(client):
    membership = PrescriberMembershipFactory()
    assignment = JobSeekerAssignmentFactory(prescriber_organization=membership.organization)
    client.force_login(membership.user)

    response = client.get(advisor_url(assignment), HTTP_HX_REQUEST="true")
    assertNotContains(response, "Modifier mon accompagnement")
    assertNotContains(response, "Terminer mon accompagnement")
    assert client.get(end_url(assignment), HTTP_HX_REQUEST="true").status_code == 404
