from unittest import mock

from django.test import TestCase
from django.core import mail

from anymail.exceptions import AnymailRequestsAPIError
from django_xworkflows import models as xwf_models

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.job_applications.factories import JobApplicationWithPrescriberFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.templatetags import format_filters


class JobApplicationEmailTest(TestCase):
    """Test JobApplication emails."""

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_new_for_siae
        # To.
        self.assertIn(job_application.siae.members.first().email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(
            job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body
        )
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(
            format_filters.format_phone(job_application.job_seeker.phone), email.body
        )
        self.assertIn(job_application.message, email.body)
        for job in job_application.jobs.all():
            self.assertIn(job.name, email.body)
        self.assertIn(job_application.prescriber_user.get_full_name(), email.body)
        self.assertIn(job_application.prescriber_user.email, email.body)
        self.assertIn(
            format_filters.format_phone(job_application.prescriber_user.phone),
            email.body,
        )
        self.assertIn(job_application.prescriber.name, email.body)

    def test_process_for_job_seeker(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_process_for_job_seeker
        # To.
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.siae.get_card_url(), email.body)

    def test_process_for_prescriber(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_process_for_prescriber
        # To.
        self.assertIn(job_application.prescriber_user.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.get_full_name(), email.body)
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.siae.get_card_url(), email.body)

    def test_accept_for_job_seeker(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_accept_for_job_seeker
        # To.
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.siae.get_card_url(), email.body)

    def test_accept_for_prescriber(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_accept_for_prescriber
        # To.
        self.assertIn(job_application.prescriber_user.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.job_seeker.get_full_name(), email.body)
        self.assertIn(job_application.answer, email.body)
        self.assertIn(job_application.siae.get_card_url(), email.body)

    def test_reject_for_job_seeker(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_reject_for_job_seeker
        # To.
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)

    def test_reject_for_prescriber(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_reject_for_prescriber
        # To.
        self.assertIn(job_application.prescriber_user.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)


class JobApplicationWorkflowTest(TestCase):
    """Test JobApplication workflow."""

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_send(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        self.assertTrue(job_application.state.is_new)
        job_application.send()
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(job_application.state.is_pending_processing)

    def test_send_fail(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all()
        )
        with mock.patch("django.core.mail.message.EmailMessage.send") as send:
            send.side_effect = AnymailRequestsAPIError()
            with self.assertRaises(xwf_models.AbortTransition):
                job_application.send()
            self.assertTrue(job_application.state.is_new)

    def test_process(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all(),
            state=JobApplicationWorkflow.STATE_PENDING_PROCESSING,
        )
        self.assertTrue(job_application.state.is_pending_processing)
        job_application.process()
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(job_application.state.is_processing)

    def test_accept(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all(),
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        self.assertTrue(job_application.state.is_processing)
        answer = "Lorem ipsum dolor sit amet"
        job_application.accept(answer=answer)
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(job_application.state.is_accepted)
        self.assertEqual(job_application.answer, answer)

    def test_reject(self):
        job_application = JobApplicationWithPrescriberFactory(
            jobs=Appellation.objects.all(),
            state=JobApplicationWorkflow.STATE_PENDING_PROCESSING,
        )
        self.assertTrue(job_application.state.is_pending_processing)
        answer = "Lorem ipsum dolor sit amet"
        job_application.reject(answer=answer)
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(job_application.state.is_rejected)
        self.assertEqual(job_application.answer, answer)
