from django.contrib.auth.models import AnonymousUser

from itou.utils.urls import get_zendesk_form_url
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.testing import get_request


class TestZendeskUrl:
    def test_anonymous_user(self, snapshot):
        request = get_request(AnonymousUser())
        assert get_zendesk_form_url(request) == snapshot

    def test_job_seeker(self, snapshot):
        request = get_request(JobSeekerFactory(for_snapshot=True))
        assert get_zendesk_form_url(request) == snapshot

    def test_labor_inspector(self, snapshot):
        request = get_request(
            LaborInspectorFactory(
                for_snapshot=True,
                membership=True,
                membership__institution__name="Ministère des affaires étranges",
            )
        )
        assert get_zendesk_form_url(request) == snapshot

    def test_employer(self, snapshot):
        request = get_request(
            EmployerFactory(
                for_snapshot=True,
                membership=True,
                membership__company__for_snapshot=True,
            )
        )
        assert get_zendesk_form_url(request) == snapshot

        # fallback on company phone
        request.user.phone = None
        assert get_zendesk_form_url(request) == snapshot(name="company_phone")

    def test_prescriber(self, snapshot):
        request = get_request(PrescriberFactory(for_snapshot=True))
        assert get_zendesk_form_url(request) == snapshot(name="no organization")

        PrescriberMembershipFactory(
            user=request.user,
            organization__for_snapshot=True,
            organization__phone="0123456789",
        )
        request = get_request(request.user)
        assert get_zendesk_form_url(request) == snapshot(name="with organization")

        # fallback on organization phone
        request.user.phone = None
        assert get_zendesk_form_url(request) == snapshot(name="organization phone")
