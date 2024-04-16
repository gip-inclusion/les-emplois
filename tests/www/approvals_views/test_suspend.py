from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from pytest_django.asserts import assertContains

from itou.approvals.models import Suspension
from itou.employee_record.enums import Status
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.approvals_views.forms import SuspensionForm
from tests.approvals.factories import SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase, parse_response_to_soup


@pytest.mark.usefixtures("unittest_compatibility")
class ApprovalSuspendViewTest(TestCase):
    @pytest.mark.ignore_unknown_variable_template_error
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
        detail_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
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

        back_url = reverse("approvals:suspension_action_choice", kwargs={"suspension_id": suspension.pk})
        redirect_url = reverse("approvals:detail", kwargs={"pk": suspension.approval_id})
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
        assert response.status_code == 200
        form = parse_response_to_soup(
            response,
            selector="div.c-form",
            replace_in_attr=[
                ("href", f"/approvals/detail/{approval.pk}", "/approvals/detail/[PK of Approval]"),
                (
                    "href",
                    f"/approvals/suspension/{suspension.pk}/action/",
                    "/approvals/suspension/[PK of Suspension]/action/",
                ),
            ],
        )
        assert str(form) == self.snapshot(name="delete_suspension_form")
        assert response.context["reset_url"] == redirect_url

        lost_days = (timezone.localdate() - start_at).days + 1  # including start and end dates
        assertContains(response, f"Réduire la durée restante de ce PASS IAE de {lost_days} jour")

        post_data = {"confirm": "true"}

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        assert response.url == redirect_url

        assert 0 == approval.suspension_set.count()


class ApprovalSuspendActionChoiceViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.job_application = JobApplicationFactory(
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )
        cls.approval = cls.job_application.approval
        cls.employer = cls.job_application.to_company.members.first()
        cls.suspension = SuspensionFactory(
            approval=cls.approval, start_at=today, end_at=today + relativedelta(days=10), created_by=cls.employer
        )
        cls.url = reverse("approvals:suspension_action_choice", kwargs={"suspension_id": cls.suspension.pk})

    def test_not_current_siae(self):
        self.client.force_login(JobSeekerFactory())

        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_not_current_suspension(self):
        self.client.force_login(self.employer)

        response = self.client.get(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.pk + 1})
        )
        assert response.status_code == 404

    def test_suspension_cannot_be_handled(self):
        self.client.force_login(self.employer)
        with mock.patch("itou.approvals.models.Suspension.can_be_handled_by_siae", return_value=False):
            response = self.client.get(self.url)
        assert response.status_code == 403

    def test_context(self):
        self.client.force_login(self.employer)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context["suspension"] == self.suspension
        assert response.context["back_url"] == reverse("approvals:detail", kwargs={"pk": self.suspension.approval_id})

    def test_input_action_names(self):
        self.client.force_login(self.employer)

        response = self.client.get(self.url)
        assertContains(
            response,
            (
                '<input class="form-check-input" type="radio" name="action" '
                'id="endDateRadios" value="update_enddate" checked>'
            ),
            status_code=200,
        )
        assertContains(
            response,
            '<input class="form-check-input" type="radio" name="action" id="deleteRadios" value="delete">',
            status_code=200,
        )

    def test_post_delete(self):
        self.client.force_login(self.employer)

        response = self.client.post(self.url, data={"action": "delete"})
        assert response.url == reverse("approvals:suspension_delete", kwargs={"suspension_id": self.suspension.pk})

    def test_post_enddate(self):
        self.client.force_login(self.employer)

        response = self.client.post(self.url, data={"action": "update_enddate"})
        assert response.url == reverse(
            "approvals:suspension_update_enddate", kwargs={"suspension_id": self.suspension.pk}
        )

    def test_post_enddate_with_invalid_action_parameter(self):
        self.client.force_login(self.employer)

        response = self.client.post(self.url, data={"action": "unknown_action"})
        assert response.status_code == 400


class ApprovalSuspendUpdateEndDateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.job_application = JobApplicationFactory(
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=20),
        )
        cls.approval = cls.job_application.approval
        cls.employer = cls.job_application.to_company.members.first()
        cls.suspension = SuspensionFactory(
            approval=cls.approval,
            start_at=today - relativedelta(days=10),
            end_at=today + relativedelta(days=10),
            created_by=cls.employer,
        )
        cls.url = reverse("approvals:suspension_update_enddate", kwargs={"suspension_id": cls.suspension.pk})

    def test_not_current_siae(self):
        self.client.force_login(JobSeekerFactory())

        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_not_current_suspension(self):
        self.client.force_login(self.employer)

        response = self.client.get(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.pk + 1})
        )
        assert response.status_code == 404

    def test_suspension_cannot_be_handled(self):
        self.client.force_login(self.employer)
        with mock.patch("itou.approvals.models.Suspension.can_be_handled_by_siae", return_value=False):
            response = self.client.get(self.url)
        assert response.status_code == 403

    def test_context(self):
        self.client.force_login(self.employer)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context["suspension"] == self.suspension
        assert response.context["back_url"] == reverse(
            "approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.id}
        )
        assert response.context["reset_url"] == reverse("approvals:detail", kwargs={"pk": self.suspension.approval_id})
        assert "form" in response.context

        form = response.context["form"]
        assert form.initial["first_day_back_to_work"] == timezone.localdate()
        assert form.siae == self.job_application.to_company
        assert form.approval == self.approval
        assert form.instance == self.suspension
        assert form.fields["first_day_back_to_work"].widget.attrs == {
            "min": self.suspension.start_at + relativedelta(days=1),
            "max": self.suspension.end_at,
        }

    def test_context_on_first_day_of_suspension(self):
        self.suspension.start_at = timezone.localdate()
        self.suspension.save()
        self.client.force_login(self.employer)

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert "form" in response.context

        form = response.context["form"]
        assert form.initial["first_day_back_to_work"] == timezone.localdate() + relativedelta(days=1)

    def test_post(self):
        self.client.force_login(self.employer)

        response = self.client.post(self.url, data={"first_day_back_to_work": timezone.localdate()})
        assert response.url == reverse("approvals:detail", kwargs={"pk": self.suspension.approval_id})
        self.suspension.refresh_from_db()
        assert self.suspension.end_at == timezone.localdate() - relativedelta(days=1)
        assert self.suspension.updated_by == self.employer

    def test_post_with_invalid_endate(self):
        self.client.force_login(self.employer)

        # MIN
        response = self.client.post(
            self.url, data={"first_day_back_to_work": self.suspension.start_at - relativedelta(days=1)}
        )
        assert response.status_code == 200
        assert "form" in response.context

        form = response.context["form"]
        assert form.is_valid() is False
        assert "first_day_back_to_work" in form.errors
        assert (
            form.errors["first_day_back_to_work"][0]
            == "Vous ne pouvez pas saisir une date de réintégration antérieure au début de la suspension."
        )

        # MAX
        response = self.client.post(
            self.url, data={"first_day_back_to_work": self.suspension.end_at + relativedelta(days=1)}
        )
        assert response.status_code == 200
        assert "form" in response.context

        form = response.context["form"]
        assert form.is_valid() is False
        assert "first_day_back_to_work" in form.errors
        assert (
            form.errors["first_day_back_to_work"][0]
            == "Vous ne pouvez pas saisir une date de réintégration postérieure à la fin de la suspension."
        )
