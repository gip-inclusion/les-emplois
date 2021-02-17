from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta

from django.core import mail
# from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import SuspensionFactory
from itou.approvals.models import Approval, Prolongation, Suspension
from itou.eligibility.factories import EligibilityDiagnosisFactory

# from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.factories import DEFAULT_PASSWORD

from .pdfshift_mock import BITES_FILE


# from requests import exceptions as requests_exceptions


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDownloadApprovalAsPDF(TestCase):
    @patch("pdfshift.convert", return_value=BITES_FILE)
    def test_download_job_app_approval_as_pdf(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        siae_member = job_application.to_siae.members.first()
        job_seeker = job_application.job_seeker
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

        response = self.client.get(
            reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
        )

        # Temporarily disable approval download due to PDF Shift unavailability.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:index"))

        # self.assertEqual(response.status_code, 200)
        # self.assertEqual(response.status_code, 200)
        # self.assertIn("pdf", response.get("Content-Type"))

    # def test_impossible_download_when_approval_is_missing(self, *args, **kwargs):
    #     """
    #     The button to download an approval is show only when
    #     certain conditions are met.
    #     Nevertheless, don't trust the client. Make sure we raise an error
    #     if the same conditions are not met in this view.
    #     """
    #     # Create a job application without an approval.
    #     job_application = JobApplicationFactory()
    #     siae_member = job_application.to_siae.members.first()
    #     job_seeker = job_application.job_seeker
    #     EligibilityDiagnosisFactory(job_seeker=job_seeker)

    #     self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)
    #     response = self.client.get(
    #         reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
    #     )
    #     self.assertEqual(response.status_code, 404)

    # @patch("pdfshift.convert", side_effect=requests_exceptions.ConnectionError)
    # def test_pdfshift_api_is_down(self, *args, **kwargs):
    #     job_application = JobApplicationWithApprovalFactory()
    #     siae_member = job_application.to_siae.members.first()
    #     job_seeker = job_application.job_seeker
    #     EligibilityDiagnosisFactory(job_seeker=job_seeker)

    #     self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

    #     with self.assertRaises(ConnectionAbortedError):
    #         self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))

    # @patch("pdfshift.convert", return_value=BITES_FILE)
    # @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", False)
    # def test_download_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
    #     job_application = JobApplicationWithApprovalFactory()
    #     siae_member = job_application.to_siae.members.first()

    #     # An approval has been delivered but it does not come from Itou.
    #     # Therefore, the linked diagnosis exists but is not in our database.
    #     # Don't create a diagnosis.
    #     # EligibilityDiagnosisFactory(job_seeker=job_seeker)

    #     self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

    #     response = self.client.get(
    #         reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk})
    #     )

    #     self.assertEqual(response.status_code, 200)
    #     self.assertIn("pdf", response.get("Content-Type"))

    # @patch("itou.approvals.models.CommonApprovalMixin.originates_from_itou", True)
    # def test_no_download_if_missing_diagnosis(self, *args, **kwargs):
    #     job_application = JobApplicationWithApprovalFactory()
    #     siae_member = job_application.to_siae.members.first()

    #     # An approval has been delivered by Itou but there is no diagnosis.
    #     # It should raise an error.
    #     # EligibilityDiagnosisFactory(job_seeker=job_seeker)

    #     self.client.login(username=siae_member.email, password=DEFAULT_PASSWORD)

    #     with self.assertRaises(ObjectDoesNotExist):
    #         self.client.get(reverse("approvals:approval_as_pdf", kwargs={"job_application_id": job_application.pk}))


class ApprovalSuspendViewTest(TestCase):
    def test_suspend_approval(self):
        """
        Test the creation of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        self.assertEqual(0, approval.suspension_set.count())

        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        start_at = today
        end_at = today + relativedelta(days=10)

        post_data = {
            "start_at": start_at.strftime("%d/%m/%Y"),
            "end_at": end_at.strftime("%d/%m/%Y"),
            "reason": Suspension.Reason.SICKNESS,
            "reason_explanation": "",
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], True)

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, approval.suspension_set.count())
        suspension = approval.suspension_set.first()
        self.assertEqual(suspension.created_by, siae_user)

    def test_update_suspension(self):
        """
        Test the update of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        siae_user = job_application.to_siae.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=siae_user)

        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_update", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        new_end_at = end_at + relativedelta(days=30)

        post_data = {
            "start_at": suspension.start_at.strftime("%d/%m/%Y"),
            "end_at": new_end_at.strftime("%d/%m/%Y"),
            "reason": suspension.reason,
            "reason_explanation": suspension.reason_explanation,
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, approval.suspension_set.count())
        suspension = approval.suspension_set.first()
        self.assertEqual(suspension.updated_by, siae_user)
        self.assertEqual(suspension.end_at, new_end_at)

    def test_delete_suspension(self):
        """
        Test the deletion of a suspension.
        """

        today = timezone.now().date()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )

        approval = job_application.approval
        siae_user = job_application.to_siae.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=siae_user)

        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"confirm": "true"}

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(0, approval.suspension_set.count())


class ApprovalProlongViewTest(TestCase):
    def test_prolong_approval(self):
        """
        Test the creation of a prolongation.
        """

        today = timezone.now().date()

        # Set "now" to be "after" the day approval is open to prolongation.
        approval_end_at = (
            today
            + relativedelta(months=Approval.PROLONGATION_PERIOD_BEFORE_APPROVAL_END_MONTHS)
            - relativedelta(days=1)
        )
        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
            approval__end_at=approval_end_at,
        )

        approval = job_application.approval
        self.assertEqual(0, approval.suspension_set.count())

        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:prolong", kwargs={"approval_id": approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        reason = Prolongation.Reason.SENIOR
        end_at = Prolongation.get_max_end_at(approval.end_at, reason=reason)

        post_data = {
            "end_at": end_at.strftime("%d/%m/%Y"),
            "reason": reason,
            "reason_explanation": "Reason explanation is required.",
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], True)

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, back_url)

        self.assertEqual(1, approval.prolongation_set.count())
        prolongation = approval.prolongation_set.first()
        self.assertEqual(prolongation.created_by, siae_user)

        # Itou staff should receive an email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Demande de prolongation sur Itou", email.subject)
        self.assertIn("Nouvelle demande de prolongation sur Itou", email.body)
