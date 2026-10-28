import random
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.approvals.models import Suspension
from itou.employee_record.enums import Status
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.approvals_views.forms import SuspensionForm
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestApprovalSuspendView:
    def test_suspend_approval(self, client, caplog):
        """
        Test the creation of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )

        # Ensure that the job_application cannot be canceled.
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        approval = job_application.approval
        assert 0 == approval.suspension_set.count()

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        back_url = reverse("dashboard:index")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        url = f"{url}?{params}"

        response = client.get(url)
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
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, back_url)

        assert 1 == approval.suspension_set.count()
        suspension = approval.suspension_set.first()
        assert suspension.created_by == employer
        assert caplog.messages[2] == (
            f"user={employer.pk} created suspension={suspension.pk} (approval={approval.pk}) "
            f"from {start_at} to {end_at}"
        )

        # Ensure suspension reason is not displayed in details page
        detail_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(detail_url)
        assertNotContains(response, suspension.get_reason_display())

    def test_create_suspension_without_end_date(self):
        # Only test form validation (faster)

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
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
            sent_by_prescriber_alone=True,
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

    def test_update_suspension(self, client, snapshot, caplog):
        """
        Test the update of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )

        approval = job_application.approval
        employer = job_application.to_company.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=employer)

        client.force_login(employer)

        back_url = reverse("dashboard:index")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_update", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(url)
        assert response.status_code == 200

        cancel_button = parse_response_to_soup(
            response,
            selector='a[aria-label="Annuler la saisie de ce formulaire"]',
        )
        assert cancel_button.attrs["href"] == back_url

        new_end_at = end_at + relativedelta(days=30)

        post_data = {
            "start_at": suspension.start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_at": new_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": suspension.reason,
            "reason_explanation": suspension.reason_explanation,
        }

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, back_url)

        assert 1 == approval.suspension_set.count()
        suspension = approval.suspension_set.first()
        assert suspension.updated_by == employer
        assert suspension.end_at == new_end_at

        assert caplog.messages[1] == (
            f"user={employer.pk} updated suspension={suspension.pk} (approval={approval.pk}) dates "
            f"from {[str(start_at), str(end_at)]} to {[str(start_at), str(new_end_at)]}"
        )

    def test_delete_suspension(self, client, snapshot, caplog):
        """
        Test the deletion of a suspension.
        """

        today = timezone.localdate()

        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )

        approval = job_application.approval
        employer = job_application.to_company.members.first()
        start_at = today
        end_at = today + relativedelta(days=10)

        suspension = SuspensionFactory(approval=approval, start_at=start_at, end_at=end_at, created_by=employer)

        client.force_login(employer)

        back_url = reverse("search:home")
        redirect_url = reverse("approvals:details", kwargs={"public_id": suspension.approval.public_id})
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:suspension_delete", kwargs={"suspension_id": suspension.pk})
        url = f"{url}?{params}"

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(url)
        assert response.status_code == 200
        form = parse_response_to_soup(
            response,
            selector="div.c-form",
            replace_in_attr=[
                ("href", f"/approvals/details/{approval.public_id}", "/approvals/detail/[Public ID of Approval]"),
                (
                    "href",
                    f"/approvals/suspension/{suspension.pk}/action/",
                    "/approvals/suspension/[PK of Suspension]/action/",
                ),
            ],
        )
        assert pretty_indented(form) == snapshot(name="delete_suspension_form")
        assert response.context["reset_url"] == back_url

        lost_days = (timezone.localdate() - start_at).days + 1  # including start and end dates
        assertContains(response, f"Réduire la durée restante de ce PASS IAE de {lost_days} jour")

        post_data = {"confirm": "true"}

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assert response.url == redirect_url

        assert 0 == approval.suspension_set.count()
        assert caplog.messages[1] == (
            f"user={employer.pk} deleted suspension={suspension.pk} (approval={approval.pk}) which ranged "
            f"from {suspension.start_at} to {suspension.end_at}"
        )

    ALERT_TEXT = "Nous avons détecté, d’après les données de l’extranet IAE 2.0 de l’ASP"

    @pytest.mark.parametrize(
        "end_date_offset",
        [
            pytest.param(None, id="no_end_date"),
            pytest.param(relativedelta(months=1), id="future_end_date"),
        ],
    )
    def test_contract_reasons_disabled_with_ongoing_contract(self, client, end_date_offset):
        today = timezone.localdate()
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )
        approval = job_application.approval
        end_date = today + end_date_offset if end_date_offset is not None else None
        ContractFactory(job_seeker=approval.user, end_date=end_date)

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        response = client.get(url)
        assertContains(response, self.ALERT_TEXT)

        # The two following reasons cannot be chosen if there is an ongoing contract.
        for reason in [Suspension.Reason.BROKEN_CONTRACT, Suspension.Reason.FINISHED_CONTRACT]:
            post_data = {
                "start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "end_at": (today + relativedelta(days=10)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": reason,
                "reason_explanation": "",
            }
            form = SuspensionForm(approval=approval, siae=job_application.to_company, data=post_data)
            assert not form.is_valid()
            assert "reason" in form.errors

        # Other reasons stay valid.
        form = SuspensionForm(
            approval=approval,
            siae=job_application.to_company,
            data={
                "start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "end_at": (today + relativedelta(days=10)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": Suspension.Reason.SUSPENDED_CONTRACT,
                "reason_explanation": "",
            },
        )
        assert form.is_valid()

    @pytest.mark.parametrize(
        "with_contract",
        [
            pytest.param(False, id="no_contract"),
            pytest.param(True, id="with_ignored_contract"),
        ],
    )
    def test_contract_reasons_enabled_without_ongoing_contract(self, client, with_contract):
        today = timezone.localdate()
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )
        approval = job_application.approval
        if with_contract:
            # Ended contract
            ContractFactory(
                job_seeker=approval.user,
                end_date=today - relativedelta(days=1),
            )
            # ongoing contract on an inactive siae
            ContractFactory(
                job_seeker=approval.user,
                company__convention__is_active=False,
                end_date=None,
            )

        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:suspend", kwargs={"approval_id": approval.pk})
        response = client.get(url)
        assertNotContains(response, self.ALERT_TEXT)

        form = SuspensionForm(
            approval=approval,
            siae=job_application.to_company,
            data={
                "start_at": today.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "end_at": (today + relativedelta(days=10)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": random.choice([Suspension.Reason.BROKEN_CONTRACT, Suspension.Reason.FINISHED_CONTRACT]),
                "reason_explanation": "",
            },
        )
        assert form.is_valid()

    def test_update_keeps_previously_saved_contract_reason_with_ongoing_contract(self, client):
        today = timezone.localdate()
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            hiring_start_at=today - relativedelta(days=1),
        )
        approval = job_application.approval
        ContractFactory(job_seeker=approval.user, company=job_application.to_company, end_date=None)

        employer = job_application.to_company.members.first()
        suspension = SuspensionFactory(
            approval=approval,
            start_at=today,
            end_at=today + relativedelta(days=10),
            reason=Suspension.Reason.BROKEN_CONTRACT,
            created_by=employer,
        )

        # An already stored reason must stay selectable/editable...
        form = SuspensionForm(
            approval=approval,
            siae=job_application.to_company,
            instance=suspension,
            data={
                "start_at": suspension.start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "end_at": suspension.end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": Suspension.Reason.BROKEN_CONTRACT,
                "reason_explanation": "",
            },
        )
        assert form.is_valid()
        # ...while the other reason must stay disabled.
        assert form.fields["reason"].widget.disabled_values == {Suspension.Reason.FINISHED_CONTRACT.value}


class TestApprovalSuspendActionChoiceView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        today = timezone.localdate()
        self.job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
        )
        self.approval = self.job_application.approval
        self.employer = self.job_application.to_company.members.first()
        self.suspension = SuspensionFactory(
            approval=self.approval, start_at=today, end_at=today + relativedelta(days=10), created_by=self.employer
        )
        self.url = reverse("approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.pk})

    def test_not_current_siae(self, client):
        client.force_login(JobSeekerFactory())

        response = client.get(self.url)
        assert response.status_code == 404

    def test_not_current_suspension(self, client):
        client.force_login(self.employer)

        response = client.get(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.pk + 1})
        )
        assert response.status_code == 404

    def test_suspension_cannot_be_handled(self, client):
        client.force_login(self.employer)
        with mock.patch("itou.approvals.models.Suspension.can_be_handled_by_siae", return_value=False):
            response = client.get(self.url)
        assert response.status_code == 403

    def test_context(self, client, snapshot):
        client.force_login(self.employer)

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(self.url)
        assert response.status_code == 200
        assert response.context["suspension"] == self.suspension
        assert response.context["back_url"] == reverse(
            "approvals:details", kwargs={"public_id": self.suspension.approval.public_id}
        )

    def test_input_action_names(self, client):
        client.force_login(self.employer)

        response = client.get(self.url)
        assertContains(
            response,
            (
                '<input class="form-check-input" type="radio" name="action" '
                'id="endDateRadios" value="update_enddate" checked>'
            ),
            status_code=200,
            html=True,
        )
        assertContains(
            response,
            '<input class="form-check-input" type="radio" name="action" id="deleteRadios" value="delete">',
            status_code=200,
            html=True,
        )

    def test_post_delete(self, client):
        client.force_login(self.employer)

        response = client.post(self.url, data={"action": "delete"})
        assertRedirects(
            response,
            reverse(
                "approvals:suspension_delete",
                kwargs={"suspension_id": self.suspension.pk},
                query={
                    "back_url": reverse("approvals:details", kwargs={"public_id": self.suspension.approval.public_id})
                },
            ),
        )

    def test_post_enddate(self, client):
        client.force_login(self.employer)

        response = client.post(self.url, data={"action": "update_enddate"})
        assertRedirects(
            response,
            reverse(
                "approvals:suspension_update_enddate",
                kwargs={"suspension_id": self.suspension.pk},
                query={
                    "back_url": reverse("approvals:details", kwargs={"public_id": self.suspension.approval.public_id})
                },
            ),
        )

    def test_post_enddate_with_invalid_action_parameter(self, client):
        client.force_login(self.employer)

        response = client.post(self.url, data={"action": "unknown_action"})
        assert response.status_code == 400


class TestApprovalSuspendUpdateEndDateView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        today = timezone.localdate()
        self.job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=20),
        )
        self.approval = self.job_application.approval
        self.employer = self.job_application.to_company.members.first()
        self.suspension = SuspensionFactory(
            approval=self.approval,
            start_at=today - relativedelta(days=10),
            end_at=today + relativedelta(days=10),
            created_by=self.employer,
        )
        self.url = reverse("approvals:suspension_update_enddate", kwargs={"suspension_id": self.suspension.pk})

    def test_not_current_siae(self, client):
        client.force_login(JobSeekerFactory())

        response = client.get(self.url)
        assert response.status_code == 404

    def test_not_current_suspension(self, client):
        client.force_login(self.employer)

        response = client.get(
            reverse("approvals:suspension_action_choice", kwargs={"suspension_id": self.suspension.pk + 1})
        )
        assert response.status_code == 404

    def test_suspension_cannot_be_handled(self, client):
        client.force_login(self.employer)
        with mock.patch("itou.approvals.models.Suspension.can_be_handled_by_siae", return_value=False):
            response = client.get(self.url)
        assert response.status_code == 403

    def test_context(self, client, snapshot):
        client.force_login(self.employer)

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(self.url)
        assert response.status_code == 200
        assert response.context["suspension"] == self.suspension
        assert response.context["secondary_url"] == reverse(
            "approvals:suspension_action_choice",
            kwargs={"suspension_id": self.suspension.id},
            query={"back_url": reverse("approvals:details", kwargs={"public_id": self.suspension.approval.public_id})},
        )

        assert response.context["reset_url"] == reverse(
            "approvals:details", kwargs={"public_id": self.suspension.approval.public_id}
        )
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

    def test_context_on_first_day_of_suspension(self, client):
        self.suspension.start_at = timezone.localdate()
        self.suspension.save()
        client.force_login(self.employer)

        response = client.get(self.url)
        assert response.status_code == 200
        assert "form" in response.context

        form = response.context["form"]
        assert form.initial["first_day_back_to_work"] == timezone.localdate() + relativedelta(days=1)

    def test_post(self, client, caplog):
        client.force_login(self.employer)

        old_end_at = self.suspension.end_at
        new_end_at = timezone.localdate() - relativedelta(days=1)

        response = client.post(self.url, data={"first_day_back_to_work": timezone.localdate()})
        assert response.url == reverse("approvals:details", kwargs={"public_id": self.suspension.approval.public_id})
        self.suspension.refresh_from_db()
        assert self.suspension.end_at == new_end_at
        assert self.suspension.updated_by == self.employer
        assert caplog.messages[0] == (
            f"user={self.employer.pk} updated suspension={self.suspension.pk} "
            f"(approval={self.suspension.approval.pk}) end date from "
            f"{str(old_end_at)} to {str(new_end_at)}"
        )

    def test_post_with_invalid_endate(self, client):
        client.force_login(self.employer)

        # MIN
        response = client.post(
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
        response = client.post(
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


def test_suspend_other_company_returns_404(client):
    approval = ApprovalFactory()
    other_user = CompanyMembershipFactory(company__subject_to_iae_rules=True).user
    client.force_login(other_user)
    response = client.get(reverse("approvals:suspend", kwargs={"approval_id": approval.pk}))
    assert response.status_code == 404


@pytest.mark.parametrize(
    "url_name",
    [
        "approvals:suspension_action_choice",
        "approvals:suspension_update",
        "approvals:suspension_update_enddate",
        "approvals:suspension_delete",
    ],
)
def test_suspension_actions_on_other_company_returns_404(client, url_name):
    suspension = SuspensionFactory()
    other_user = CompanyMembershipFactory(company__subject_to_iae_rules=True).user
    client.force_login(other_user)
    response = client.get(reverse(url_name, kwargs={"suspension_id": suspension.pk}))
    assert response.status_code == 404
