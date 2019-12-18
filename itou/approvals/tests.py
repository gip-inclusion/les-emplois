import datetime

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase

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
        approval = ApprovalFactory(number="999991900030")
        self.assertEqual(Approval.get_next_number(), 999991900031)

    def test_accepted_by(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        approval = ApprovalFactory(
            number="999991900030", job_application=job_application
        )
        self.assertEqual(approval.accepted_by, job_application.to_siae.members.first())

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
