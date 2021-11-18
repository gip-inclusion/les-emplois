from dateutil.relativedelta import relativedelta
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.models import Approval, Prolongation
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.approvals_views.forms import DeclareProlongationForm


class ApprovalProlongationTest(TestCase):
    def setUp(self):
        """
        Create test objects.
        """

        self.prescriber_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()
        self.prescriber = self.prescriber_organization.members.first()

        today = timezone.now().date()

        # Set "now" to be "after" the day approval is open to prolongation.
        approval_end_at = (
            today + relativedelta(months=Approval.IS_OPEN_TO_PROLONGATION_BOUNDARIES_MONTHS) - relativedelta(days=1)
        )
        self.job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
            approval__end_at=approval_end_at,
        )
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        self.assertEqual(0, self.approval.prolongation_set.count())

    def test_form_without_pre_existing_instance(self):
        """
        Test the default state of `DeclareProlongationForm`.
        """
        form = DeclareProlongationForm(approval=self.approval, siae=self.siae, data={})

        self.assertIsNone(form.fields["reason"].initial)

        # Ensure that `form.instance` is populated so that `Prolongation.clean()`
        # is triggered from within the form validation step with the right data.
        self.assertEqual(form.instance.declared_by_siae, self.siae)
        self.assertEqual(form.instance.approval, self.approval)
        self.assertEqual(form.instance.start_at, Prolongation.get_start_at(self.approval))

    def test_prolong_approval_view(self):
        """
        Test the creation of a prolongation.
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        reason = Prolongation.Reason.SENIOR
        end_at = Prolongation.get_max_end_at(self.approval.end_at, reason=reason)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "reason_explanation": "Reason explanation is required.",
            "email": self.prescriber.email,
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

        self.assertEqual(1, self.approval.prolongation_set.count())

        prolongation = self.approval.prolongation_set.first()
        self.assertEqual(prolongation.created_by, self.siae_user)
        self.assertEqual(prolongation.declared_by, self.siae_user)
        self.assertEqual(prolongation.declared_by_siae, self.job_application.to_siae)
        self.assertEqual(prolongation.validated_by, self.prescriber)
        self.assertEqual(prolongation.reason, post_data["reason"])

        # An email should have been sent to the chosen authorized prescriber.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(len(email.to), 1)
        self.assertEqual(email.to[0], post_data["email"])

    def test_prolong_approval_view_without_prescriber(self):
        """
        Test the creation of a prolongation without prescriber.
        """

        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)

        back_url = "/"
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preview"], False)

        reason = Prolongation.Reason.COMPLETE_TRAINING
        end_at = Prolongation.get_max_end_at(self.approval.end_at, reason=reason)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
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

        self.assertEqual(1, self.approval.prolongation_set.count())

        prolongation = self.approval.prolongation_set.first()
        self.assertEqual(prolongation.created_by, self.siae_user)
        self.assertEqual(prolongation.declared_by, self.siae_user)
        self.assertEqual(prolongation.declared_by_siae, self.job_application.to_siae)
        self.assertIsNone(prolongation.validated_by)
        self.assertEqual(prolongation.reason, post_data["reason"])

        # No email should have been sent.
        self.assertEqual(len(mail.outbox), 0)
