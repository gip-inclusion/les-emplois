from functools import partial

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains

from itou.users.models import NirModificationRequest
from itou.utils.urls import get_absolute_url
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


def test_access_for_job_seeker(client):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    response = client.get(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "factory,status_code",
    [
        (None, 302),
        (JobSeekerFactory, 404),  # Trying to access another job seeker's form
        (PrescriberFactory, 404),
        (partial(PrescriberFactory, membership=True, membership__organization__authorized=True), 200),
        (partial(EmployerFactory, with_company=True), 200),
        (ItouStaffFactory, 403),
        (partial(LaborInspectorFactory, membership=True), 403),
    ],
)
def test_access(client, factory, status_code):
    job_seeker = JobSeekerFactory()
    if factory:
        client.force_login(factory())
    response = client.get(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    )
    assert response.status_code == status_code


@pytest.mark.parametrize(
    "data",
    [
        {"nir": ""},
        {"nir": "190031398700953"},  # Same as original
    ],
)
def test_create_request_invalid_nir(client, data):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    client.post(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id}), data=data
    )

    assert NirModificationRequest.objects.count() == 0


def test_create_with_ongoing_request(client, mailoutbox):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")

    # Ongoing request
    nir_modification_request = NirModificationRequest.objects.create(
        jobseeker_profile=job_seeker.jobseeker_profile,
        nir="111111111111318",
        requested_by=job_seeker,
    )
    data = {"nir": "111111111111120"}
    response = client.post(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id}), data=data
    )

    assertContains(response, "Une demande est déjà en cours de traitement pour ce candidat.")
    assert NirModificationRequest.objects.count() == 1
    assert len(mailoutbox) == 0

    # Closed request
    nir_modification_request.processed_at = timezone.now()
    nir_modification_request.save()
    data = {"nir": "111111111111120"}
    response = client.post(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id}), data=data
    )

    assert response.status_code == 302  # Redirected to back_url
    assert NirModificationRequest.objects.count() == 2
    assert len(mailoutbox) == 1


def test_create_request_valid(client, mailoutbox):
    user = PrescriberFactory(membership=True, membership__organization__authorized=True)
    client.force_login(user)
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    data = {"nir": "1 11 11 11 111 111 20"}  # .format-nir does that.
    client.post(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id}), data=data
    )

    nir_modification_request = NirModificationRequest.objects.first()
    assert nir_modification_request.jobseeker_profile == job_seeker.jobseeker_profile
    assert nir_modification_request.requested_by == user
    assert nir_modification_request.processed_at is None
    assert nir_modification_request.nir == "111111111111120"

    [email] = mailoutbox
    admin_url = get_absolute_url(
        reverse("admin:users_nirmodificationrequest_change", args=(nir_modification_request.pk,))
    )
    assert admin_url in email.body
