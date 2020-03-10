from unittest import mock

from django.test import TestCase
from django.urls import reverse
from requests import exceptions as requests_exceptions

from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationWithApprovalFactory,
)
from itou.users.factories import DEFAULT_PASSWORD

from .pdfshift_mock import BITES_FILE


class TestDownloadApprovalAsPDF(TestCase):
    @mock.patch("pdfshift.convert", return_value=BITES_FILE)
    def test_download_job_app_approval_as_pdf(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse(
                "approvals:approval_as_pdf",
                kwargs={"job_application_id": job_application.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    def test_impossible_download_when_approval_is_missing(self):
        """
        The button to download an approval is show only when
        certain conditions are met.
        Nevertheless, don't trust the client. Make sure we raise an error
        if the same conditions are not met in this view.
        """
        # Create a job application without an approval.
        job_application = JobApplicationFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)
        response = self.client.get(
            reverse(
                "approvals:approval_as_pdf",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    @mock.patch("pdfshift.convert", side_effect=requests_exceptions.ConnectionError)
    def test_pdfshift_api_is_down(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with self.assertRaises(ConnectionAbortedError):
            self.client.get(
                reverse(
                    "approvals:approval_as_pdf",
                    kwargs={"job_application_id": job_application.pk},
                )
            )
