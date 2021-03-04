from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD


class EditContractTest(TestCase):
    """
    Checks:
    - updating a job application hiring start date when it starts in the future
    - coherence of PASS start / end date
    """

    def setUp(self):
        siae1 = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Elliot")
        siae2 = SiaeWithMembershipAndJobsFactory(name="Duke of Hazard Corp.", membership__user__first_name="Roscoe")

        self.user1 = siae1.members.get(first_name="Elliot")
        self.user2 = siae2.members.get(first_name="Roscoe")

        # JA with creation of a new approval
        tomorrow = (timezone.now() + relativedelta(days=1)).date()
        self.job_application_1 = JobApplicationWithApprovalFactory(
            to_siae=siae1, hiring_start_at=tomorrow, approval__start_at=tomorrow
        )

        # JA with an old approval
        delta = relativedelta(months=23)
        self.old_job_application = JobApplicationWithApprovalFactory(to_siae=siae2, created_at=timezone.now() - delta)
        approval = self.old_job_application.approval
        approval.start_at = self.old_job_application.created_at.date()

        self.job_application_2 = JobApplicationWithApprovalFactory(
            to_siae=siae2,
            job_seeker=self.old_job_application.job_seeker,
            approval=approval,
        )

        self.url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_1.id})
        self.old_url = reverse(
            "apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_2.id}
        )

    def test_approval_can_be_postponed(self):
        self.assertTrue(self.job_application_1.approval.can_postpone_start_date)
        self.assertFalse(self.old_job_application.approval.can_postpone_start_date)

    def test_future_contract_date(self):
        """
        Checks possibility of changing hiring start date to a future date.
        """
        self.client.login(username=self.user1.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (timezone.now() + relativedelta(days=10)).date()
        future_end_date = (timezone.now() + relativedelta(days=15)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": future_end_date.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
        self.assertEqual(response.url, next_url)

        self.job_application_1.refresh_from_db()

        self.assertEqual(self.job_application_1.hiring_start_at, future_start_date)
        self.assertEqual(self.job_application_1.hiring_end_at, future_end_date)

    def test_past_contract_date(self):
        """
        Past contract start date are not allowed
        """
        self.client.login(username=self.user1.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (timezone.now() - relativedelta(days=10)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": self.job_application_1.hiring_end_at.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 200)

    def test_max_postpone_contract_date(self):
        """
        The contract start date can only be postponed of 30 days
        """

        self.client.login(username=self.user1.username, password=DEFAULT_PASSWORD)

        url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application_1.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (
            timezone.now() + relativedelta(days=JobApplication.MAX_CONTRACT_POSTPONE_IN_DAYS + 1)
        ).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": self.job_application_1.hiring_end_at.strftime("%d/%m/%Y"),
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

    def test_postpone_approval(self):
        """
        If hiring date is postponed,
        approval start date must be updated accordingly (if there is an approval)
        """
        self.client.login(username=self.user1.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        future_start_date = (timezone.now() + relativedelta(days=20)).date()
        future_end_date = (timezone.now() + relativedelta(days=60)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": future_end_date.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application_1.id})
        self.assertEqual(response.url, next_url)

        self.job_application_1.refresh_from_db()

        self.assertIsNotNone(self.job_application_1.approval)
        self.assertEqual(self.job_application_1.hiring_start_at, self.job_application_1.approval.start_at)

    def test_start_date_with_previous_approval(self):
        """
        When the job application is linked to a previous approval,
        check that approval dates are not updated if the hiring date change
        """
        self.client.login(username=self.user2.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.old_url)

        future_start_date = (timezone.now() + relativedelta(days=5)).date()
        future_end_date = (timezone.now() + relativedelta(days=60)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": future_end_date.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.old_url, data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.job_application_2.hiring_start_at > self.job_application_2.approval.start_at)

    def test_do_not_update_approval(self):
        """
        Previously running approval start date must not be updated
        when postponing contract dates
        """
        self.client.login(username=self.user2.username, password=DEFAULT_PASSWORD)
        response = self.client.get(self.old_url)

        approval = self.job_application_2.approval

        future_start_date = approval.start_at + relativedelta(days=10)
        future_end_date = future_start_date + relativedelta(days=60)

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": future_end_date.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.old_url, data=post_data)
        self.assertEqual(response.status_code, 200)
