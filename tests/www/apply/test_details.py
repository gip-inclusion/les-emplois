import random
from functools import partial

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.job_applications.enums import JobApplicationState
from tests.companies.factories import CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


def test_missing_job_seeker_info(client):
    job_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        job_seeker__phone="",
        job_seeker__email=None,
        job_seeker__jobseeker_profile__birthdate=None,
        job_seeker__jobseeker_profile__nir="",
        job_seeker__jobseeker_profile__pole_emploi_id="",
        message="Motivation est mon deuxième prénom.",
        answer="Réponse au candidat.",
    )
    user = EmployerFactory(membership=True, membership__company=job_application.to_company)
    client.force_login(user)
    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertNotContains(response, "None")


@pytest.mark.parametrize(
    "factory,assertion",
    [
        (partial(JobApplicationFactory, sent_by_authorized_prescriber=True), assertContains),
        (partial(JobApplicationFactory, sent_by_prescriber=True), assertContains),
        (partial(JobApplicationFactory, sent_by_another_employer=True), assertNotContains),
    ],
)
def test_prescriber_see_history_box(client, factory, assertion):
    job_application = factory()
    client.force_login(job_application.sender)
    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assertion(response, "<h3>Suivi du candidat</h3>", html=True)


def test_hide_old_applications_to_employers(client, subtests):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    employer = membership.user

    hidden_application = JobApplicationFactory(
        to_company=company,
        created_at=timezone.now() - timezone.timedelta(days=365 * 2),
        sent_by_authorized_prescriber=True,
        state=random.choice(list(set(JobApplicationState.values) - {JobApplicationState.ACCEPTED})),
    )
    job_seeker = hidden_application.job_seeker
    prescriber = hidden_application.sender
    prescriber_organization = hidden_application.sender_prescriber_organization

    visible_applications = [
        # recent enough
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            created_at=timezone.now() - timezone.timedelta(days=365 * 2 - 1),
            sent_by_authorized_prescriber=True,
            sender=prescriber,
            sender_prescriber_organization=prescriber_organization,
            state=random.choice(list(set(JobApplicationState.values) - {JobApplicationState.ACCEPTED})),
        ),
        # old but accepted
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            created_at=timezone.now() - timezone.timedelta(days=365 * 2 + 1),
            sent_by_authorized_prescriber=True,
            sender=prescriber,
            sender_prescriber_organization=prescriber_organization,
            state=JobApplicationState.ACCEPTED,
        ),
    ]

    client.force_login(employer)
    response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": hidden_application.pk}))
    assert response.status_code == 404
    for job_app in visible_applications:
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_app.pk}))
        assertContains(response, job_app.job_seeker.get_inverted_full_name())

    client.force_login(prescriber)
    for job_app in [hidden_application] + visible_applications:
        response = client.get(reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_app.pk}))
        assertContains(response, job_app.job_seeker.get_inverted_full_name())

    client.force_login(job_seeker)
    for job_app in [hidden_application] + visible_applications:
        response = client.get(reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_app.pk}))
        assertContains(response, company.display_name)


def edit_jobseeker_info_button(url, job_application):
    edit_job_seeker_info_url = (
        reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_public_id": job_application.job_seeker.public_id}
        )
        + f"?back_url={url}&from_application={job_application.pk}"
    )
    job_seeker_name = job_application.job_seeker.get_inverted_full_name()

    return f"""
            <a href="{edit_job_seeker_info_url}"
               class="btn btn-ico btn-outline-primary"
               aria-label="Modifier les informations personnelles de {job_seeker_name}">
                <i class="ri-pencil-line fw-medium" aria-hidden="true"></i>
                <span>Modifier</span>
            </a>
        """


@pytest.mark.parametrize(
    "factory,assertion",
    [
        (partial(JobApplicationFactory, sent_by_authorized_prescriber=True), assertContains),
        (partial(JobApplicationFactory, sent_by_prescriber=True), assertNotContains),
        (partial(JobApplicationFactory, sent_by_another_employer=True), assertContains),
    ],
)
def test_display_edit_jobseeker_info_button(client, factory, assertion):
    job_application = factory()
    client.force_login(job_application.sender)
    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertion(response, edit_jobseeker_info_button(url, job_application), html=True)


@pytest.mark.parametrize("created_by_prescriber,assertion", [(True, assertContains), (False, assertNotContains)])
def test_display_edit_jobseeker_info_button_as_unauthorized_prescriber(client, created_by_prescriber, assertion):
    prescriber = PrescriberFactory(membership=True)
    job_seeker = JobSeekerFactory(created_by=prescriber if created_by_prescriber else None)
    job_application = JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=job_seeker, sender=prescriber)
    client.force_login(prescriber)
    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertion(response, edit_jobseeker_info_button(url, job_application), html=True)
