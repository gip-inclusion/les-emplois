from unittest.mock import PropertyMock, patch

from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication
from itou.users.factories import DEFAULT_PASSWORD, UserFactory

from .pdfshift_mock import BITES_FILE


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDownloadApprovalAsPDF(TestCase):
    @patch("itou.utils.pdf.HtmlToPdf.html_to_bytes", return_value=BITES_FILE)
    def test_download_job_app_approval_as_pdf(self, *args, **kwargs):
        """
        Given an existing job application with a PASS IAE and a diagnosis,
        when trying to download it as PDF, then it works.
        """
        job_application = JobApplicationWithApprovalFactory()

        siae_member = job_application.to_siae.members.first()
        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    def test_impossible_download_when_approval_is_missing(self, *args, **kwargs):
        """
        Given an existing job application without a PASS IAE,
        when trying to download it as PDF, then a 404 should be raised.
        """
        job_application = JobApplicationFactory()

        siae_member = job_application.to_siae.members.first()
        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )
        # `can_download_approval_as_pdf` should fail and trigger a 404.
        self.assertEqual(response.status_code, 404)

    @patch("itou.utils.pdf.HtmlToPdf.html_to_bytes", return_value=BITES_FILE)
    def test_download_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        """
        Given an existing job application with an approval delivered by Pôle emploi
        but no diagnosis, when trying to download it as PDF, then it works.
        """

        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        job_application = JobApplicationWithApprovalFactory(
            eligibility_diagnosis=None, approval__number="625741810181"
        )

        siae_member = job_application.to_siae.members.first()
        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    @patch("itou.utils.pdf.HtmlToPdf.html_to_bytes", return_value=BITES_FILE)
    def test_download_approval_missing_diagnosis_ai(self, *args, **kwargs):
        """
        Given an existing job application with an approval delivered by Itou
        when importing AI employees, when an AI tries to download it as PDF, it works.
        """

        # On November 30th, 2021, AI were delivered approvals without a diagnosis.
        # See itou.users.management.commands.import_ai_employees.
        approval_created_at = timezone.datetime(2021, 11, 30, tzinfo=timezone.utc)
        approval_created_by = UserFactory(email="celine@hello-birds.com")
        job_application = JobApplicationWithApprovalFactory(
            eligibility_diagnosis=None,
            approval__created_at=approval_created_at,
            approval__created_by=approval_created_by,
        )

        siae_member = job_application.to_siae.members.first()
        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    def test_no_download_if_missing_diagnosis(self, *args, **kwargs):
        """
        Given an existing job application with an approval delivered by Itou but no
        diagnosis, when trying to download it as PDF, then it raises an error.
        """
        job_application = JobApplicationWithApprovalFactory(eligibility_diagnosis=None)

        siae_member = job_application.to_siae.members.first()
        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with self.assertRaises(ObjectDoesNotExist):
            self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))
