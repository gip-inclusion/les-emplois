import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertRedirects

from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestEmailTrackingConsent:
    url = reverse("dashboard:email_tracking_consent")

    @pytest.mark.parametrize("factory", [EmployerFactory, JobSeekerFactory])
    def test_get(self, client, factory, snapshot):
        client.force_login(factory(email_tracking_consent_updated_at=None))
        response = client.get(self.url)
        assertContains(response, "<h1>Suivi de l’ouverture de vos e-mails</h1>", html=True)
        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot

    @pytest.mark.parametrize(
        "post_data, expected_consent",
        [
            ({"email_tracking_consent": "True"}, True),
            ({"email_tracking_consent": "False"}, False),
        ],
    )
    @freeze_time("2026-10-09T10:00:00+02:00")
    def test_post(self, client, post_data, expected_consent):
        user = JobSeekerFactory(email_tracking_consent_updated_at=None)
        client.force_login(user)
        next_url = reverse("dashboard:edit_user_info")
        response = client.post(reverse("dashboard:email_tracking_consent", query={"next": next_url}), post_data)
        assertRedirects(response, next_url, fetch_redirect_response=False)
        user.refresh_from_db()
        assert user.email_tracking_consent is expected_consent
        assert user.email_tracking_consent_updated_at == datetime.datetime(
            2026, 10, 9, 10, tzinfo=ZoneInfo(settings.TIME_ZONE)
        )

    def test_post_with_unsafe_next_url(self, client):
        client.force_login(JobSeekerFactory(email_tracking_consent_updated_at=None))
        response = client.post(
            reverse("dashboard:email_tracking_consent", query={"next": "https://evil.com"}),
            {"email_tracking_consent": "True"},
        )
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)

    def test_post_without_answer(self, client):
        user = JobSeekerFactory(email_tracking_consent_updated_at=None)
        client.force_login(user)
        response = client.post(self.url)
        assert response.status_code == 200
        assert response.context["form"].errors == {"email_tracking_consent": ["Ce champ est obligatoire."]}
        user.refresh_from_db()
        assert user.email_tracking_consent_updated_at is None

    @pytest.mark.parametrize("method", ["get", "post"])
    def test_already_answered(self, client, method):
        user = JobSeekerFactory(email_tracking_consent=False)
        answered_at = user.email_tracking_consent_updated_at
        client.force_login(user)
        next_url = reverse("dashboard:edit_user_info")
        url = reverse("dashboard:email_tracking_consent", query={"next": next_url})
        if method == "get":
            response = client.get(url)
        else:
            response = client.post(url, {"email_tracking_consent": "True"})
        assertRedirects(response, next_url, fetch_redirect_response=False)
        user.refresh_from_db()
        assert user.email_tracking_consent is False
        assert user.email_tracking_consent_updated_at == answered_at
