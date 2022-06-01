import datetime
from unittest.mock import patch

import httpx
import respx
from django.test import TestCase, override_settings
from django.utils import timezone

from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.job_applications.models import pole_emploi_api_client
from itou.users.factories import JobSeekerFactory
from itou.utils.apis.pole_emploi import PoleEmploiApiClient
from itou.utils.mocks.pole_emploi import (
    PE_API_MAJPASS_RESULT_ERROR_MOCK,
    PE_API_MAJPASS_RESULT_OK_MOCK,
    PE_API_RECHERCHE_MANY_RESULTS_MOCK,
    PE_API_RECHERCHE_RESULT_KNOWN_MOCK,
)


@override_settings(
    API_ESD={
        "BASE_URL": "https://base.domain",
        "AUTH_BASE_URL": "https://authentication-domain.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class JobApplicationNotifyPoleEmploiIntegrationTest(TestCase):
    def setUp(self):
        self.api_client = PoleEmploiApiClient()
        respx.post(self.api_client.token_url).mock(
            return_value=httpx.Response(200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600})
        )

    def test_invalid_job_seeker_for_pole_emploi(self):
        """
        Error case: our job seeker is not valid (from PoleEmploi’s point of view: here, the NIR is missing)
         - We do not even call the APIs
         - no entry should be added to the notification log database
        """
        now = timezone.now()
        job_seeker = JobSeekerFactory(nir="")
        job_application = JobApplicationWithApprovalFactory(job_seeker=job_seeker)
        job_application.notify_pole_emploi(at=now)
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_error")
        self.assertEqual(job_application.approval.pe_notification_time, now)
        self.assertEqual(job_application.approval.pe_notification_endpoint, "rech_individu")
        self.assertEqual(job_application.approval.pe_notification_exit_code, "MISSING_DATA")

    @respx.mock
    def test_notification_accepted_nominal(self):
        now = timezone.now()
        respx.post(self.api_client.recherche_individu_url).mock(
            return_value=httpx.Response(200, json=PE_API_RECHERCHE_RESULT_KNOWN_MOCK)
        )
        respx.post(self.api_client.mise_a_jour_url).mock(
            return_value=httpx.Response(200, json=PE_API_MAJPASS_RESULT_OK_MOCK)
        )
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationWithApprovalFactory(job_seeker=job_seeker)
        job_application.notify_pole_emploi(at=now)
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_success")
        self.assertEqual(job_application.approval.pe_notification_time, now)
        self.assertEqual(job_application.approval.pe_notification_endpoint, None)
        self.assertEqual(job_application.approval.pe_notification_exit_code, None)

    @respx.mock
    def test_notification_stays_pending_if_approval_starts_after_today(self):
        now = timezone.now()
        respx.post(self.api_client.recherche_individu_url).mock(
            return_value=httpx.Response(200, json=PE_API_RECHERCHE_RESULT_KNOWN_MOCK)
        )
        respx.post(self.api_client.mise_a_jour_url).mock(
            return_value=httpx.Response(200, json=PE_API_MAJPASS_RESULT_OK_MOCK)
        )
        tomorrow = (now + datetime.timedelta(days=1)).date()
        job_application = JobApplicationWithApprovalFactory(approval__start_at=tomorrow)
        with self.assertLogs("itou.job_applications.models") as logs:
            job_application.notify_pole_emploi(at=now)
        self.assertIn(
            f"notify_pole_emploi approval={job_application.approval} "
            f"start_at={job_application.approval.start_at} "
            f"starts after today={now.date()}",
            logs.output[0],
        )
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_pending")
        self.assertEqual(job_application.approval.pe_notification_time, None)
        self.assertEqual(job_application.approval.pe_notification_endpoint, None)
        self.assertEqual(job_application.approval.pe_notification_exit_code, None)

    @patch.object(pole_emploi_api_client, "expires_at", None)
    @respx.mock
    def test_notification_goes_to_retry_if_there_is_a_timeout(self):

        now = timezone.now()
        respx.post(self.api_client.token_url).mock(side_effect=httpx.ConnectTimeout)
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationWithApprovalFactory(job_seeker=job_seeker)
        job_application.notify_pole_emploi(at=now)
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_should_retry")
        self.assertEqual(job_application.approval.pe_notification_time, now)
        self.assertEqual(job_application.approval.pe_notification_endpoint, None)
        self.assertEqual(job_application.approval.pe_notification_exit_code, None)

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_rech_individu(self):
        now = timezone.now()
        respx.post(self.api_client.recherche_individu_url).mock(
            return_value=httpx.Response(200, json=PE_API_RECHERCHE_MANY_RESULTS_MOCK)
        )
        respx.post(self.api_client.mise_a_jour_url).mock(
            return_value=httpx.Response(200, json=PE_API_MAJPASS_RESULT_OK_MOCK)
        )
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationWithApprovalFactory(job_seeker=job_seeker)
        job_application.notify_pole_emploi(at=now)
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_error")
        self.assertEqual(job_application.approval.pe_notification_time, now)
        self.assertEqual(job_application.approval.pe_notification_endpoint, "rech_individu")
        self.assertEqual(job_application.approval.pe_notification_exit_code, "S002")

    @respx.mock
    def test_notification_goes_to_error_if_something_goes_wrong_with_maj_pass(self):
        now = timezone.now()
        respx.post(self.api_client.recherche_individu_url).mock(
            return_value=httpx.Response(200, json=PE_API_RECHERCHE_RESULT_KNOWN_MOCK)
        )
        respx.post(self.api_client.mise_a_jour_url).mock(
            return_value=httpx.Response(200, json=PE_API_MAJPASS_RESULT_ERROR_MOCK)
        )
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationWithApprovalFactory(job_seeker=job_seeker)
        job_application.notify_pole_emploi(at=now)
        job_application.approval.refresh_from_db()
        self.assertEqual(job_application.approval.pe_notification_status, "notification_error")
        self.assertEqual(job_application.approval.pe_notification_time, now)
        self.assertEqual(job_application.approval.pe_notification_endpoint, "maj_pass")
        self.assertEqual(job_application.approval.pe_notification_exit_code, "S022")
