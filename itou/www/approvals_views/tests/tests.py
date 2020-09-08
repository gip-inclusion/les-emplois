from unittest.mock import PropertyMock, patch

from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.urls import reverse
from requests import exceptions as requests_exceptions

from itou.eligibility.factories import PrescriberEligibilityDiagnosisFactory
from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication
from itou.users.factories import DEFAULT_PASSWORD

from .pdfshift_mock import BITES_FILE


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDownloadApprovalAsPDF(TestCase):
    @patch("pdfshift.convert", return_value=BITES_FILE)
    def test_download_job_app_approval_as_pdf(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    def test_impossible_download_when_approval_is_missing(self, *args, **kwargs):
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
        PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)
        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )
        self.assertEqual(response.status_code, 404)

    @patch("pdfshift.convert", side_effect=requests_exceptions.ConnectionError)
    def test_pdfshift_api_is_down(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with self.assertRaises(ConnectionAbortedError):
            self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))

    @patch("pdfshift.convert", return_value=BITES_FILE)
    @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", False)
    def test_download_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()

        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        # Don't create a diagnosis.
        # PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("pdf", response.get("Content-Type"))

    @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", True)
    def test_no_download_if_missing_diagnosis(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()

        # An approval has been delivered by Itou but there is no diagnosis.
        # It should raise an error.
        # PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        with self.assertRaises(ObjectDoesNotExist):
            self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))
