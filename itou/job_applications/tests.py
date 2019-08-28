from unittest import mock

from django.test import TestCase, override_settings
from django.core import mail
from django.utils.html import escape

from anymail.exceptions import AnymailRequestsAPIError
from django_xworkflows import models as xwf_models

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.job_applications.factories import JobRequestWithPrescriberFactory
from itou.job_applications.models import JobRequestWorkflow


class JobRequestEmailTest(TestCase):
    """Test JobRequest emails."""

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        email = job_request.email_new_for_siae
        # To.
        self.assertIn(job_request.siae.members.first().email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_request.job_seeker.first_name, email.body)
        self.assertIn(job_request.job_seeker.last_name, email.body)
        self.assertIn(job_request.job_seeker.email, email.body)
        self.assertIn(escape(job_request.motivation_message), email.body)
        for job in job_request.jobs.all():
            self.assertIn(escape(job.name), email.body)
        self.assertIn(job_request.prescriber_user.get_full_name(), email.body)
        self.assertIn(job_request.prescriber_user.email, email.body)
        self.assertIn(job_request.prescriber.name, email.body)

    def test_accept_for_job_seeker(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        email = job_request.email_accept_for_job_seeker
        # To.
        self.assertIn(job_request.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_request.job_seeker.first_name, email.body)
        self.assertIn(job_request.siae.name, email.body)
        self.assertIn(job_request.acceptance_message, email.body)
        self.assertIn(job_request.siae.get_card_url(), email.body)

    def test_accept_for_prescriber(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        email = job_request.email_accept_for_prescriber
        # To.
        self.assertIn(job_request.prescriber_user.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_request.siae.name, email.body)
        self.assertIn(job_request.job_seeker.get_full_name(), email.body)
        self.assertIn(job_request.acceptance_message, email.body)
        self.assertIn(job_request.siae.get_card_url(), email.body)


class JobRequestWorkflowTest(TestCase):
    """Test JobRequest workflow."""

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_send(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        # Current status.
        self.assertTrue(job_request.state.is_new)
        # Trigger transition.
        job_request.send()
        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        # New status.
        self.assertTrue(job_request.state.is_pending_answer)

    def test_send_fail(self):
        job_request = JobRequestWithPrescriberFactory(jobs=Appellation.objects.all())
        with mock.patch("django.core.mail.message.EmailMessage.send") as send:
            send.side_effect = AnymailRequestsAPIError()
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
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # New status.
        self.assertTrue(job_request.state.is_accepted)

        # print('-' * 80)
        # print(mail.outbox[0].subject)
        # print('-' * 10)
        # print(mail.outbox[0].body)
        # print('-' * 80)
        # print(mail.outbox[1].subject)
        # print('-' * 10)
        # print(mail.outbox[1].body)
