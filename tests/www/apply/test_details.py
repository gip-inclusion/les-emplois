import random
from functools import partial

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.job_applications.enums import JobApplicationState
from tests.companies.factories import CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory


def test_missing_job_seeker_info(client):
    job_application = JobApplicationFactory(
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
        (partial(JobApplicationFactory, sent_by_authorized_prescriber_organisation=True), assertContains),
        (
            partial(
                JobApplicationFactory,
                sent_by_authorized_prescriber_organisation=True,
                sender_prescriber_organization__authorized=False,
            ),
            assertContains,
        ),
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
        sent_by_authorized_prescriber_organisation=True,
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
            sent_by_authorized_prescriber_organisation=True,
            sender=prescriber,
            sender_prescriber_organization=prescriber_organization,
            state=random.choice(list(set(JobApplicationState.values) - {JobApplicationState.ACCEPTED})),
        ),
        # old but accepted
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            created_at=timezone.now() - timezone.timedelta(days=365 * 2 + 1),
            sent_by_authorized_prescriber_organisation=True,
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


def test_job_seeker_referent_heading(client):
    DEFAULT_HEADING = "<h3>Qui accompagne ce candidat ?</h3>"
    JOB_SEEKER_HEADING = "<h3>Qui m'accompagne ?</h3>"
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)
    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertContains(response, DEFAULT_HEADING, html=True)
    assertNotContains(response, JOB_SEEKER_HEADING, html=True)

    client.force_login(job_application.job_seeker)
    url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertNotContains(response, DEFAULT_HEADING, html=True)
    assertContains(response, JOB_SEEKER_HEADING, html=True)
