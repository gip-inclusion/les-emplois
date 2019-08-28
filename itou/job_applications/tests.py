from django.test import TestCase, override_settings
from django.core import mail
from django.utils.html import escape

from django_xworkflows import models as xwf_models

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.job_applications.factories import JobRequestWithPrescriberFactory
from itou.job_applications.models import JobRequestWorkflow

# log = job_request.logs.first()
# print('-' * 80)
# print(log.timestamp)
# print(log.user)
# print(log.user_id)


class JobRequestModelStateWorkflowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_send(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())

        # Check current status.
        self.assertTrue(job_request.state.is_new)

        # Trigger transition.
        job_request.send()

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]

        # Check email content.
        self.assertIn(job_request.job_seeker.first_name, email.body)
        self.assertIn(job_request.job_seeker.last_name, email.body)
        self.assertIn(job_request.job_seeker.email, email.body)
        self.assertIn(escape(job_request.motivation_message), email.body)
        for job in job_request.jobs.all():
            self.assertIn(escape(job.name), email.body)
        self.assertIn(job_request.prescriber_user.get_full_name(), email.body)
        self.assertIn(job_request.prescriber_user.email, email.body)
        self.assertIn(job_request.prescriber.name, email.body)

        # Check new status.
        self.assertTrue(job_request.state.is_pending_answer)

    @override_settings(
        EMAIL_BACKEND="anymail.backends.mailjet.EmailBackend",
        ANYMAIL={"MAILJET_API_KEY": "DUMMY", "MAILJET_SECRET_KEY": "DUMMY"},
    )
    def test_send_fail(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        with self.assertRaises(xwf_models.AbortTransition):
            job_request.send()
        self.assertTrue(job_request.state.is_new)

    def test_accept(self):
        job_request = JobRequestWithPrescriberFactory(
            jobs=Appellation.objects.all(),
            state=JobRequestWorkflow.STATE_PENDING_ANSWER,
        )

        # Current status.
        self.assertTrue(job_request.state.is_pending_answer)

        # Trigger transition.
        job_request.accept()

        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        email1 = mail.outbox[0]
        email2 = mail.outbox[1]

        # print("-" * 80)
        # print(email1.subject)
        # print(email1.body)
        # print("-" * 80)
        # print(email2.subject)
        # print(email2.body)
