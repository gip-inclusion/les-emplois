from unittest import mock

from django.test import TestCase
from django.urls import reverse

from itou.users.factories import DEFAULT_PASSWORD
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory

from .pdfshift_mock import BITES_FILE


class TestDownloadApprovalAsPDF(TestCase):
    def test_download_job_app_approval_as_pdf(self):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with mock.patch("pdfshift.convert", return_value=BITES_FILE):
            response = self.client.get(
                reverse(
                    "approvals:approval_as_pdf",
                    kwargs={"job_application_id": job_application.pk},
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))
