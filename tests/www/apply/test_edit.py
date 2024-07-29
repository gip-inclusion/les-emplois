from types import NoneType

import pytest
from dateutil.relativedelta import relativedelta
from django.http.request import urlencode
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time
from pytest_django.asserts import assertRedirects

from itou.job_applications.enums import ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL, JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.widgets import DuetDatePickerWidget
from tests.companies.factories import CompanyFactory, CompanyWithMembershipAndJobsFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import TestCase


class EditContractTest(TestCase):
    """
    Checks:
    - updating a job application hiring start date when it starts in the future
    - coherence of PASS start / end date
    """

    def setUp(self):
        super().setUp()
        company_1 = CompanyWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        company_2 = CompanyWithMembershipAndJobsFactory(
            name="Duke of Hazard Corp.", membership__user__first_name="Roscoe"
        )

        self.user1 = company_1.members.get(first_name="Elliot")
        self.user2 = company_2.members.get(first_name="Roscoe")

        # JA with creation of a new approval
        tomorrow = timezone.localdate() + relativedelta(days=1)
        self.job_application_1 = JobApplicationFactory(
            with_approval=True, to_company=company_1, hiring_start_at=tomorrow, approval__start_at=tomorrow
        )

        # JA with an old approval
        delta = relativedelta(months=23)
        self.old_job_application = JobApplicationFactory(
            with_approval=True, to_company=company_2, created_at=timezone.now() - delta
        )
        approval = self.old_job_application.approval
        approval.start_at = self.old_job_application.created_at.date()

        self.job_application_2 = JobApplicationFactory(
            with_approval=True,
            to_company=company_2,
            job_seeker=self.old_job_application.job_seeker,
            approval=approval,
        )

        self.url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_1.id})
        self.old_url = reverse(
            "apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_2.id}
        )

    def test_approval_can_be_postponed(self):
        assert self.job_application_1.approval.can_postpone_start_date
        assert not self.old_job_application.approval.can_postpone_start_date

    def test_future_contract_date(self):
        """
        Checks possibility of changing hiring start date to a future date.
        """
        self.client.force_login(self.user1)

        response = self.client.get(self.url)

        assert response.status_code == 200

        future_start_date = timezone.localdate() + relativedelta(days=10)
        future_end_date = timezone.localdate() + relativedelta(days=15)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # test how hiring_end_date is displayed
        response = self.client.get(next_url)
        self.assertContains(
            response, f"<small>Fin</small><strong>{dateformat.format(future_end_date, 'd F Y')}</strong>", html=True
        )

    def test_future_contract_date_without_hiring_end_at(self):
        """
        Checks possibility of changing hiring start date to a future date, with no hiring_end_at date.
        """
        self.client.force_login(self.user1)

        response = self.client.get(self.url)

        assert response.status_code == 200

        future_start_date = timezone.localdate() + relativedelta(days=11)
        future_end_date = None

        # empty "hiring_end_at"
        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # no "hiring_end_at"
        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # test how hiring_end_date is displayed
        response = self.client.get(next_url)
        self.assertContains(response, '<small>Fin</small><i class="text-disabled">Non renseigné</i>', html=True)

    def test_past_contract_date(self):
        """
        Past contract start date are not allowed
        """
        self.client.force_login(self.user1)

        response = self.client.get(self.url)

        assert response.status_code == 200

        future_start_date = timezone.localdate() - relativedelta(days=10)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": self.job_application_1.hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        assert response.status_code == 200

    def test_max_postpone_contract_date(self):
        """
        The contract start date can only be postponed of 30 days
        """

        self.client.force_login(self.user1)

        url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_1.id})
        response = self.client.get(url)

        assert response.status_code == 200

        future_start_date = timezone.localdate() + relativedelta(days=JobApplication.MAX_CONTRACT_POSTPONE_IN_DAYS + 1)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": self.job_application_1.hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(url, data=post_data)
        assert response.status_code == 200

    def test_postpone_approval(self):
        """
        If hiring date is postponed,
        approval start date must be updated accordingly (if there is an approval)
        """
        self.client.force_login(self.user1)
        response = self.client.get(self.url)

        future_start_date = timezone.localdate() + relativedelta(days=20)
        future_end_date = timezone.localdate() + relativedelta(days=60)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.approval is not None
        assert self.job_application_1.hiring_start_at == self.job_application_1.approval.start_at

    def test_start_date_with_previous_approval(self):
        """
        When the job application is linked to a previous approval,
        check that approval dates are not updated if the hiring date change
        """
        self.client.force_login(self.user2)
        response = self.client.get(self.old_url)

        future_start_date = timezone.localdate() + relativedelta(days=5)
        future_end_date = timezone.localdate() + relativedelta(days=60)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.old_url, data=post_data)

        assert response.status_code == 302
        assert self.job_application_2.hiring_start_at > self.job_application_2.approval.start_at

    def test_do_not_update_approval(self):
        """
        Previously running approval start date must not be updated
        when postponing contract dates
        """
        self.client.force_login(self.user2)
        response = self.client.get(self.old_url)

        approval = self.job_application_2.approval

        future_start_date = approval.start_at + relativedelta(days=10)
        future_end_date = future_start_date + relativedelta(days=60)

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.old_url, data=post_data)
        assert response.status_code == 200


@pytest.mark.parametrize(
    "archived_at_func,expected_func,viewname",
    [
        (timezone.now, NoneType, "apply:unarchive"),
        (NoneType, timezone.now, "apply:archive"),
    ],
)
@freeze_time()
class TestArchiveView:
    def test_access(self, client, archived_at_func, expected_func, viewname):
        archived_at = archived_at_func()
        other_company = CompanyFactory(with_membership=True)
        job_app = JobApplicationFactory(archived_at=archived_at, state=JobApplicationState.REFUSED)
        url = reverse(viewname, args=(job_app.pk,))

        # Anonymous users cannot access.
        response = client.post(url)
        assertRedirects(response, f"{reverse('account_login')}?{urlencode({'next': url})}")
        job_app.refresh_from_db()
        assert job_app.archived_at == archived_at

        def assert_post_fails_for_user(user):
            client.force_login(user)
            response = client.post(url)
            assert response.status_code == 404
            job_app.refresh_from_db()
            assert job_app.archived_at == archived_at

        assert_post_fails_for_user(job_app.job_seeker)
        assert_post_fails_for_user(job_app.sender)
        assert_post_fails_for_user(other_company.members.get())

        client.force_login(job_app.to_company.members.get())
        response = client.post(url)
        assertRedirects(response, reverse("apply:details_for_company", args=(job_app.pk,)))
        job_app.refresh_from_db()
        assert job_app.archived_at == expected_func()

    def test_already_in_target_state(self, client, archived_at_func, expected_func, viewname):
        target_archived_at = expected_func()
        company = CompanyWithMembershipAndJobsFactory()
        employer = company.members.get()
        job_app = JobApplicationFactory(
            to_company=company,
            archived_at=target_archived_at,
            archived_by=employer if target_archived_at else None,
            state=JobApplicationState.REFUSED,
        )
        client.force_login(employer)
        response = client.post(reverse(viewname, args=(job_app.pk,)))
        assertRedirects(response, reverse("apply:details_for_company", args=(job_app.pk,)))
        job_app.refresh_from_db()
        assert job_app.archived_at == target_archived_at

    def test_only_selected_job_application(self, client, archived_at_func, expected_func, viewname):
        archived_at = archived_at_func()
        company = CompanyWithMembershipAndJobsFactory()
        [job_app1, job_app2] = JobApplicationFactory.create_batch(
            2,
            to_company=company,
            archived_at=archived_at,
            state=JobApplicationState.REFUSED,
        )
        client.force_login(company.members.get())
        response = client.post(reverse(viewname, args=(job_app2.pk,)))
        assertRedirects(response, reverse("apply:details_for_company", args=(job_app2.pk,)))
        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        assert job_app1.archived_at == archived_at
        assert job_app2.archived_at == expected_func()


@pytest.mark.parametrize("state", JobApplicationState.values)
def test_archive_view_states(client, state):
    job_app = JobApplicationFactory(state=state)
    employer = job_app.to_company.members.get()
    client.force_login(employer)
    response = client.post(reverse("apply:archive", args=(job_app.pk,)))
    if state in ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL:
        assertRedirects(response, reverse("apply:details_for_company", args=(job_app.pk,)))
        job_app.refresh_from_db()
        assert job_app.archived_at is not None
        assert job_app.archived_by == employer
    else:
        assert response.status_code == 404
        job_app.refresh_from_db()
        assert job_app.archived_at is None
        assert job_app.archived_by is None
