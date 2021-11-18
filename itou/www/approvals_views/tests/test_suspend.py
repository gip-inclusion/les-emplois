from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import SuspensionFactory
from itou.approvals.models import Suspension
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.factories import DEFAULT_PASSWORD
from itou.utils.widgets import DuetDatePickerWidget


class ApprovalSuspendViewTest(TestCase):
    def test_suspend_approval(self):
        """
        Test the creation of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
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
            "start_at": start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": Suspension.Reason.SUSPENDED_CONTRACT,
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

        today = timezone.localdate()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
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
            "start_at": suspension.start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": new_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
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

        today = timezone.localdate()

        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
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
