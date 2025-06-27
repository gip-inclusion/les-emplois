from functools import partial

import pytest
from django.urls import reverse

from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.mark.parametrize(
    "factory,status_code",
    [
        (None, 302),
        (JobSeekerFactory, 200),
        (PrescriberFactory, 403),
        (partial(EmployerFactory, with_company=True), 403),
        (ItouStaffFactory, 403),
        (partial(LaborInspectorFactory, membership=True), 403),
    ],
)
def test_access_for_job_seeker(client, factory, status_code):
    if factory:
        client.force_login(factory())
    response = client.get(reverse("job_seekers_views:nir_modification_request"))
    assert response.status_code == status_code


@pytest.mark.parametrize(
    "factory,status_code",
    [
        (None, 302),
        (JobSeekerFactory, 403),
        (PrescriberFactory, 200),
        (partial(EmployerFactory, with_company=True), 200),
        (ItouStaffFactory, 403),
        (partial(LaborInspectorFactory, membership=True), 403),
    ],
)
def test_access_for_proxy(client, factory, status_code):
    job_seeker = JobSeekerFactory()
    if factory:
        client.force_login(factory())
    response = client.get(
        reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    )
    assert response.status_code == status_code
