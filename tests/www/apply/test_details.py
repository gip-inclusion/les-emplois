from functools import partial

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

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
