import uuid

from django.contrib import messages
from django.urls import reverse
from pytest_django.asserts import assertMessages, assertRedirects

from tests.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory
from tests.utils.test import normalize_fields_history


def test_view(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    profile = JobSeekerProfileFactory(is_stalled=True)
    assert profile.is_stalled is True
    assert profile.is_not_stalled_anymore is None

    client.force_login(prescriber)
    response = client.post(
        reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": profile.user.public_id}),
        data={"is_not_stalled_anymore": "1"},
    )
    assertRedirects(response, reverse("job_seekers_views:list"), fetch_redirect_response=False)
    profile.refresh_from_db()
    assert profile.is_stalled is True
    assert profile.is_not_stalled_anymore is True
    assertMessages(response, [messages.Message(messages.SUCCESS, "Modification réussie")])

    response = client.post(
        reverse(
            "job_seekers_views:switch_stalled_status",
            kwargs={"public_id": profile.user.public_id},
            query={"back_url": reverse("home:hp")},
        ),
        data={"is_not_stalled_anymore": "0"},
    )
    assertRedirects(response, reverse("home:hp"), fetch_redirect_response=False)
    profile.refresh_from_db()
    assert profile.is_stalled is True
    assert profile.is_not_stalled_anymore is False
    assertMessages(response, [messages.Message(messages.SUCCESS, "Modification réussie")] * 2)

    # Also check the fields' history
    assert normalize_fields_history(profile.fields_history) == [
        {
            "before": {"is_not_stalled_anymore": None},
            "after": {"is_not_stalled_anymore": True},
            "_timestamp": "[TIMESTAMP]",
            "_context": {"user": prescriber.pk, "request_id": "[REQUEST ID]"},
        },
        {
            "before": {"is_not_stalled_anymore": True},
            "after": {"is_not_stalled_anymore": False},
            "_timestamp": "[TIMESTAMP]",
            "_context": {"user": prescriber.pk, "request_id": "[REQUEST ID]"},
        },
    ]


def test_view_access_and_error(client):
    # Needs to be logged in
    response = client.get(reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 302

    prescriber = PrescriberFactory(membership__organization__authorized=False)
    client.force_login(prescriber)

    # Needs to be a POST request
    response = client.get(reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 405
    # Needs to be an authorized prescriber
    response = client.post(reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 403

    prescriber = PrescriberFactory(membership__organization__authorized=True)
    client.force_login(prescriber)

    # Needs to be an existing jobseeker
    response = client.post(reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": uuid.uuid4()}))
    assert response.status_code == 404

    job_seeker = JobSeekerFactory()
    # Needs to be a stalled jobseeker
    response = client.post(
        reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": job_seeker.public_id})
    )
    assert response.status_code == 404

    job_seeker = JobSeekerFactory(jobseeker_profile__is_stalled=True)
    response = client.post(
        reverse("job_seekers_views:switch_stalled_status", kwargs={"public_id": job_seeker.public_id}), data={}
    )
    assertMessages(response, [messages.Message(messages.ERROR, "Modification impossible")])
