import datetime

from django.conf import settings
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.factories import JobSeekerFactory
from itou.utils.templatetags import format_filters


class JobApplicationFactoriesTest(TestCase):
    def test_job_application_sent_by_job_seeker_factory(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_JOB_SEEKER
        )
        self.assertEqual(job_application.job_seeker, job_application.sender)

    def test_job_application_sent_by_prescriber_factory(self):
        job_application = JobApplicationSentByPrescriberFactory()
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER
        )
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        self.assertIsNone(job_application.sender_prescriber_organization)

    def test_job_application_sent_by_prescriber_organization_factory(self):
        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER
        )
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization
        self.assertIn(sender, sender_prescriber_organization.members.all())
        self.assertFalse(sender_prescriber_organization.is_authorized)

    def test_job_application_sent_by_authorized_prescriber_organization_factory(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER
        )
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization
        self.assertIn(sender, sender_prescriber_organization.members.all())
        self.assertTrue(sender_prescriber_organization.is_authorized)


class JobApplicationEmailTest(TestCase):
    """Test JobApplication emails."""

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            jobs=Appellation.objects.all()
        )
        email = job_application.email_new_for_siae
        # To.
        self.assertIn(job_application.to_siae.members.first().email, email.to)
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
        self.assertIn(job_application.sender.get_full_name(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(
            format_filters.format_phone(job_application.sender.phone), email.body
        )

    def test_accept(self):

        # When sent by authorized prescriber.
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        email = job_application.email_accept
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory()
        email = job_application.email_accept
        # To.
        self.assertEqual(job_application.job_seeker.email, job_application.sender.email)
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)

    def test_accept(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            date_of_hiring=datetime.date.today(),
        )
        email = job_application.email_accept_trigger_manual_approval
        # To.
        self.assertIn(settings.ITOU_EMAIL_CONTACT, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(
            job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body
        )
        self.assertIn(job_application.to_siae.siret, email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.date_of_hiring.strftime("%d/%m/%Y"), email.body)
        self.assertIn(
            reverse(
                "admin:job_applications_jobapplication_change",
                args=[job_application.id],
            ),
            email.body,
        )
        self.assertIn(reverse("admin:approvals_approval_add"), email.body)

    def test_refuse(self):

        # When sent by authorized prescriber.
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            refusal_reason=JobApplication.REFUSAL_REASON_DID_NOT_COME
        )
        email = job_application.email_refuse
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.get_refusal_reason_display(), email.body)
        self.assertIn(job_application.answer, email.body)

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(
            refusal_reason=JobApplication.REFUSAL_REASON_DID_NOT_COME
        )
        email = job_application.email_refuse
        # To.
        self.assertEqual(job_application.job_seeker.email, job_application.sender.email)
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.get_refusal_reason_display(), email.body)
        self.assertIn(job_application.answer, email.body)


class JobApplicationWorkflowTest(TestCase):
    """Test JobApplication workflow."""

    def test_accept(self):
        user = JobSeekerFactory()
        kwargs = {
            "job_seeker": user,
            "sender": user,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
        }
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)

        self.assertEqual(user.job_applications.count(), 4)
        self.assertEqual(user.job_applications.pendind().count(), 4)

        job_application = user.job_applications.filter(
            state=JobApplicationWorkflow.STATE_PROCESSING
        ).first()
        job_application.accept()

        self.assertEqual(
            user.job_applications.filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED
            ).count(),
            1,
        )
        self.assertEqual(
            user.job_applications.filter(
                state=JobApplicationWorkflow.STATE_OBSOLETE
            ).count(),
            3,
        )

        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("Numéro d'agrément requis sur Itou", mail.outbox[1].subject)

    def test_refuse(self):
        user = JobSeekerFactory()
        kwargs = {
            "job_seeker": user,
            "sender": user,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
        }
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs
        )
        job_application.refuse()

        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Candidature déclinée", mail.outbox[0].subject)
