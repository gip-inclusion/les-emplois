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
    Checks updating a job application hiring start date when it starts in the future
    """

    def setUp(self):
        siae = SiaeWithMembershipAndJobsFactory(name="Evil Corp.", membership__user__first_name="Boss")
        boss = siae.members.get(first_name="Boss")
        job_application = JobApplicationWithApprovalFactory(to_siae=siae)

        self.siae = siae
        self.job_application = job_application
        self.boss = boss
        self.url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application.id})

    def test_future_contract_date(self):
        """
        Can't change a contract date to a past date
        """
        self.client.login(username=self.boss.username, password=DEFAULT_PASSWORD)

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

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application.id})
        self.assertEqual(response.url, next_url)

        self.job_application.refresh_from_db()

        self.assertEqual(self.job_application.hiring_start_at, future_start_date)
        self.assertEqual(self.job_application.hiring_end_at, future_end_date)

    def test_past_contract_date(self):
        """
        Past contract start date are not allowed
        """
        self.client.login(username=self.boss.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (timezone.now() - relativedelta(days=10)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": self.job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 200)

    def test_max_postpone_contract_date(self):
        """
        The contract start date can only be postponed of 30 days
        """

        self.client.login(username=self.boss.username, password=DEFAULT_PASSWORD)

        url = reverse("apply:edit_contract_start_date", kwargs={"job_application_id": self.job_application.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (
            timezone.now() + relativedelta(days=JobApplication.MAX_CONTRACT_POSTPONE_IN_DAYS + 1)
        ).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": self.job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

    def test_postpone_approval(self):
        """
        If hiring date is postponed,
        approval start date must be updated accordingly (if there is an approval)
        """
        self.client.login(username=self.boss.username, password=DEFAULT_PASSWORD)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        future_start_date = (timezone.now() + relativedelta(days=20)).date()
        future_end_date = (timezone.now() + relativedelta(days=60)).date()

        post_data = {
            "hiring_start_at": future_start_date.strftime("%d/%m/%Y"),
            "hiring_end_at": future_end_date.strftime("%d/%m/%Y"),
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": self.job_application.id})
        self.assertEqual(response.url, next_url)

        self.job_application.refresh_from_db()

        self.assertIsNotNone(self.job_application.approval)
        self.assertEqual(self.job_application.hiring_start_at, self.job_application.approval.start_at)
