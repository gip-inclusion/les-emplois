from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.models import Suspension
from itou.employee_record.enums import Status
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.approvals_views.forms import SuspensionForm
from tests.approvals.factories import SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import TestCase


class ApprovalSuspendViewTest(TestCase):
    def test_suspend_approval(self):
        """
        Test the creation of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )

        # Ensure that the job_application cannot be canceled.
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        approval = job_application.approval
        assert 0 == approval.suspension_set.count()

        employer = job_application.to_company.members.first()
        self.client.force_login(employer)

        back_url = reverse("search:employers_home")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["preview"] is False

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
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, back_url)

        assert 1 == approval.suspension_set.count()
        suspension = approval.suspension_set.first()
        assert suspension.created_by == employer

        # Ensure suspension reason is not displayed in details page
        detail_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(detail_url)
        self.assertNotContains(response, suspension.get_reason_display())

    def test_create_suspension_without_end_date(self):
        # Only test form validation (faster)

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )

        # Ensure that the job_application cannot be canceled.
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        # Fill all form data:
        # do not forget to fill `end_at` field with None (or model init will override with a default value)
        post_data = {
            "start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": None,
            "set_default_end_date": False,
            "reason": Suspension.Reason.SUSPENDED_CONTRACT,
            "reason_explanation": "",
            "preview": "1",
        }

        form = SuspensionForm(approval=job_application.approval, siae=job_application.to_company, data=post_data)

        assert not form.is_valid()
        assert form.errors["end_at"][0] is not None

        # Check 'set_default_end_date' and expect a default end date to be set
        post_data["set_default_end_date"] = True
        form = SuspensionForm(approval=job_application.approval, siae=job_application.to_company, data=post_data)

        assert form.is_valid()
        assert form.cleaned_data["end_at"] == Suspension.get_max_end_at(today)

    def test_clean_form(self):
        # Ensure `clean()` is running OK in case of `start_at` error (Sentry issue):
        today = timezone.localdate()
        start_at = today + relativedelta(days=1)

        job_application = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=today - relativedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS + 1),
        )

        post_data = {
            "start_at": start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": None,
            "set_default_end_date": False,
            "reason": Suspension.Reason.SUSPENDED_CONTRACT,
            "reason_explanation": "",
            "preview": "1",
        }
        form = SuspensionForm(approval=job_application.approval, siae=job_application.to_company, data=post_data)
        assert not form.is_valid()

    def test_update_suspension(self):
        """
        Test the update of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )

        approval = job_application.approval
        employer = job_application.to_company.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=employer)

        self.client.force_login(employer)

        back_url = reverse("search:employers_home")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_update", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        assert response.status_code == 200

        new_end_at = end_at + relativedelta(days=30)

        post_data = {
            "start_at": suspension.start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": new_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": suspension.reason,
            "reason_explanation": suspension.reason_explanation,
        }

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, back_url)

        assert 1 == approval.suspension_set.count()
        suspension = approval.suspension_set.first()
        assert suspension.updated_by == employer
        assert suspension.end_at == new_end_at

    def test_delete_suspension(self):
        """
        Test the deletion of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )

        approval = job_application.approval
        employer = job_application.to_company.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=employer)

        self.client.force_login(employer)

        back_url = reverse("search:employers_home")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {"confirm": "true"}

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, back_url)

        assert 0 == approval.suspension_set.count()
