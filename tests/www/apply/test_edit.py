from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone

from itou.job_applications.models import JobApplication
from itou.utils.widgets import DuetDatePickerWidget
from tests.job_applications.factories import JobApplicationFactory
from tests.siaes.factories import SiaeWithMembershipAndJobsFactory
from tests.utils.test import TestCase


class EditContractTest(TestCase):
    """
    Checks:
    - updating a job application hiring start date when it starts in the future
    - coherence of PASS start / end date
    """

    def setUp(self):
        super().setUp()
        siae1 = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        siae2 = SiaeWithMembershipAndJobsFactory(name="Duke of Hazard Corp.", membership__user__first_name="Roscoe")

        self.user1 = siae1.members.get(first_name="Elliot")
        self.user2 = siae2.members.get(first_name="Roscoe")

        # JA with creation of a new approval
        tomorrow = (timezone.now() + relativedelta(days=1)).date()
        self.job_application_1 = JobApplicationFactory(
            with_approval=True, to_siae=siae1, hiring_start_at=tomorrow, approval__start_at=tomorrow
        )

        # JA with an old approval
        delta = relativedelta(months=23)
        self.old_job_application = JobApplicationFactory(
            with_approval=True, to_siae=siae2, created_at=timezone.now() - delta
        )
        approval = self.old_job_application.approval
        approval.start_at = self.old_job_application.created_at.date()

        self.job_application_2 = JobApplicationFactory(
            with_approval=True,
            to_siae=siae2,
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

        future_start_date = (timezone.now() + relativedelta(days=10)).date()
        future_end_date = (timezone.now() + relativedelta(days=15)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # test how hiring_end_date is displayed
        response = self.client.get(next_url)
        self.assertContains(response, f"Fin : {future_end_date:%d}")

    def test_future_contract_date_without_hiring_end_at(self):
        """
        Checks possibility of changing hiring start date to a future date, with no hiring_end_at date.
        """
        self.client.force_login(self.user1)

        response = self.client.get(self.url)

        assert response.status_code == 200

        future_start_date = (timezone.now() + relativedelta(days=11)).date()
        future_end_date = None

        # empty "hiring_end_at"
        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # no "hiring_end_at"
        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
        self.assertRedirects(response, next_url)

        self.job_application_1.refresh_from_db()

        assert self.job_application_1.hiring_start_at == future_start_date
        assert self.job_application_1.hiring_end_at == future_end_date

        # test how hiring_end_date is displayed
        response = self.client.get(next_url)
        self.assertContains(response, "Fin : Non renseigné")

    def test_past_contract_date(self):
        """
        Past contract start date are not allowed
        """
        self.client.force_login(self.user1)

        response = self.client.get(self.url)

        assert response.status_code == 200

        future_start_date = (timezone.now() - relativedelta(days=10)).date()

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

        future_start_date = (timezone.now() + relativedelta(days=20)).date()
        future_end_date = (timezone.now() + relativedelta(days=60)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": future_end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        response = self.client.post(self.url, data=post_data)
        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
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

        future_start_date = (timezone.now() + relativedelta(days=5)).date()
        future_end_date = (timezone.now() + relativedelta(days=60)).date()

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
