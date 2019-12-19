import datetime

from dateutil.relativedelta import relativedelta

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory
from itou.approvals.models import Approval
from itou.job_applications.factories import (
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
)
from itou.job_applications.models import JobApplicationWorkflow


class ModelTest(TestCase):
    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = datetime.date.today()
        approval.end_at = datetime.date.today() - datetime.timedelta(days=365 * 2)
        with self.assertRaises(ValidationError):
            approval.save()

    def test_get_next_number(self):

        now = timezone.now().date()
        current_year = now.strftime("%y")

        # No pre-existing Approval objects.
        expected_number = f"99999{current_year}00001"
        self.assertEqual(Approval.get_next_number(), expected_number)

        # With pre-existing Approval objects.
        ApprovalFactory(number=f"99999{current_year}00038", start_at=now)
        ApprovalFactory(number=f"99999{current_year}00039", start_at=now)
        ApprovalFactory(number=f"99999{current_year}00040", start_at=now)
        expected_number = f"99999{current_year}00041"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the past.
        date_of_hiring = now - relativedelta(years=3)
        year = date_of_hiring.strftime("%y")
        ApprovalFactory(number=f"99999{year}99998", start_at=date_of_hiring)
        expected_number = f"99999{year}99999"
        self.assertEqual(Approval.get_next_number(date_of_hiring), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the future.
        date_of_hiring = now + relativedelta(years=3)
        year = date_of_hiring.strftime("%y")
        ApprovalFactory(number=f"99999{year}00020", start_at=date_of_hiring)
        expected_number = f"99999{year}00021"
        self.assertEqual(Approval.get_next_number(date_of_hiring), expected_number)
        Approval.objects.all().delete()

    def test_send_number_by_email(self):

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        approval = ApprovalFactory(job_application=job_application)

        # Delete `accept` and `accept_trigger_manual_approval` emails.
        mail.outbox = []

        approval.send_number_by_email()
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(approval.user.get_full_name(), email.subject)
        self.assertIn(approval.user.get_full_name(), email.body)
        self.assertIn(approval.number, email.body)

    def test_is_valid(self):

        # Start today, end in 2 years.
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)
