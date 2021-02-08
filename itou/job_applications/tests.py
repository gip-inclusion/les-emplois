import datetime
from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationSentBySiaeFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.job_applications.notifications import NewQualifiedJobAppSiaeNotification
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipAndJobsFactory
from itou.siaes.models import Siae
from itou.users.factories import JobSeekerFactory, SiaeStaffFactory, UserFactory
from itou.utils.templatetags import format_filters


class JobApplicationModelTest(TestCase):
    def test_eligibility_diagnosis_by_siae_required(self):
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=Siae.KIND_GEIQ
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)
        self.assertFalse(job_application.eligibility_diagnosis_by_siae_required)

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=Siae.KIND_EI
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)
        self.assertTrue(job_application.eligibility_diagnosis_by_siae_required)

    def test_accepted_by(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        user = job_application.to_siae.members.first()
        job_application.accept(user=user)
        self.assertEqual(job_application.accepted_by, user)

    def test_is_sent_by_authorized_prescriber(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentByPrescriberFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentBySiaeFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        self.assertTrue(job_application.is_sent_by_authorized_prescriber)

    @patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
    def test_can_download_approval_as_pdf(self, mock_can_be_cancelled):
        """
        A user can download an approval only when certain conditions
        are met:
        - the job_application.to_siae is subject to eligibility rules,
        - an approval exists (ie is not in the process of being delivered),
        - this approval is valid,
        - the job_application has been accepted.
        """
        job_application = JobApplicationWithApprovalFactory()
        self.assertTrue(job_application.can_download_approval_as_pdf)

        # SIAE not subject to eligibility rules.
        not_eligible_kinds = [
            choice[0] for choice in Siae.KIND_CHOICES if choice[0] not in Siae.ELIGIBILITY_REQUIRED_KINDS
        ]
        not_eligible_siae = SiaeFactory(kind=not_eligible_kinds[0])
        job_application = JobApplicationWithApprovalFactory(to_siae=not_eligible_siae)
        self.assertFalse(job_application.can_download_approval_as_pdf)

        # Application is not accepted.
        job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_OBSOLETE)
        self.assertFalse(job_application.can_download_approval_as_pdf)

        # Application accepted but without approval.
        job_application = JobApplicationFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        self.assertFalse(job_application.can_download_approval_as_pdf)

        # Approval has ended
        start = datetime.date.today() - relativedelta(years=2)
        end = start + relativedelta(years=1) - relativedelta(days=1)
        ended_approval = ApprovalFactory(start_at=start, end_at=end)

        job_application = JobApplicationWithApprovalFactory(approval=ended_approval)
        self.assertFalse(job_application.can_download_approval_as_pdf)

    def test_can_be_cancelled(self):
        today = datetime.date.today()
        cancellation_days_in_future = relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
        cancellation_period_end = today - cancellation_days_in_future

        job_application_future_ok = JobApplicationWithApprovalFactory(hiring_start_at=cancellation_period_end)
        self.assertTrue(job_application_future_ok.can_be_cancelled)

        job_application_future_not_ok = JobApplicationWithApprovalFactory(
            hiring_start_at=(cancellation_period_end - relativedelta(days=365))
        )
        self.assertFalse(job_application_future_not_ok.can_be_cancelled)


class JobApplicationQuerySetTest(TestCase):
    def test_created_in_past_hours(self):

        now = timezone.now()
        hours_ago_10 = now - timezone.timedelta(hours=10)
        hours_ago_20 = now - timezone.timedelta(hours=20)
        hours_ago_30 = now - timezone.timedelta(hours=30)

        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_10)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_20)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_30)

        self.assertEqual(JobApplication.objects.created_in_past_hours(5).count(), 0)
        self.assertEqual(JobApplication.objects.created_in_past_hours(15).count(), 1)
        self.assertEqual(JobApplication.objects.created_in_past_hours(25).count(), 2)
        self.assertEqual(JobApplication.objects.created_in_past_hours(35).count(), 3)

    def test_get_unique_fk_objects(self):
        # Create 3 job applications for 2 candidates to check
        # that `get_unique_fk_objects` returns 2 candidates.
        JobApplicationSentByJobSeekerFactory()
        job_seeker = JobSeekerFactory()
        JobApplicationSentByJobSeekerFactory.create_batch(2, job_seeker=job_seeker)

        unique_job_seekers = JobApplication.objects.get_unique_fk_objects("job_seeker")

        self.assertEqual(JobApplication.objects.count(), 3)
        self.assertEqual(len(unique_job_seekers), 2)
        self.assertEqual(type(unique_job_seekers[0]), get_user_model())


class JobApplicationFactoriesTest(TestCase):
    def test_job_application_factory(self):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_application = JobApplicationFactory(selected_jobs=Appellation.objects.all())
        self.assertEqual(job_application.selected_jobs.count(), 2)

    def test_job_application_sent_by_job_seeker_factory(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_JOB_SEEKER)
        self.assertEqual(job_application.job_seeker, job_application.sender)

    def test_job_application_sent_by_prescriber_factory(self):
        job_application = JobApplicationSentByPrescriberFactory()
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        self.assertIsNone(job_application.sender_prescriber_organization)

    def test_job_application_sent_by_prescriber_organization_factory(self):
        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization
        self.assertIn(sender, sender_prescriber_organization.members.all())
        self.assertFalse(sender_prescriber_organization.is_authorized)

    def test_job_application_sent_by_authorized_prescriber_organization_factory(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertNotEqual(job_application.job_seeker, job_application.sender)
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization
        self.assertIn(sender, sender_prescriber_organization.members.all())
        self.assertTrue(sender_prescriber_organization.is_authorized)


class JobApplicationNotificationsTest(TestCase):
    """
    Test JobApplication notifications: emails content and receivers.
    """

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            selected_jobs=Appellation.objects.all()
        )
        email = NewQualifiedJobAppSiaeNotification(job_application=job_application).email
        # To.
        self.assertIn(job_application.to_siae.members.first().email, email.to)
        self.assertEqual(len(email.to), 1)

        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.get_full_name(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.to_siae.city, email.body)
        self.assertIn(str(job_application.to_siae.pk), email.body)

    def test_new_for_prescriber(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            selected_jobs=Appellation.objects.all()
        )
        email = job_application.email_new_for_prescriber
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)

        # Subject
        self.assertIn(job_application.job_seeker.get_full_name(), email.subject)

        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.get_full_name(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)

        # Assert the Job Seeker does not have access to confidential information.
        email = job_application.email_new_for_job_seeker(base_url="http://testserver")
        self.assertIn(job_application.sender.get_full_name(), email.body)
        self.assertIn(job_application.sender_prescriber_organization.display_name, email.body)
        self.assertNotIn(job_application.sender.email, email.body)
        self.assertNotIn(format_filters.format_phone(job_application.sender.phone), email.body)

    def test_new_for_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory(selected_jobs=Appellation.objects.all())
        email = job_application.email_new_for_job_seeker(base_url="http://testserver")
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_JOB_SEEKER)

        # Subject
        self.assertIn(job_application.to_siae.display_name, email.subject)

        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.first_name, email.body)
        self.assertIn(job_application.sender.last_name, email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(reverse("account_login"), email.body)
        self.assertIn(reverse("account_reset_password"), email.body)

    def test_accept(self):

        # When sent by authorized prescriber.
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        email = job_application.email_accept
        # To.
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertIn(job_application.sender.email, email.bcc)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 1)
        # Body.
        self.assertIn(job_application.sender.first_name, email.body)
        self.assertIn(job_application.sender.last_name, email.body)
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

    def test_accept_trigger_manual_approval(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED, hiring_start_at=datetime.date.today()
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        # To.
        self.assertIn(settings.ITOU_EMAIL_CONTACT, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.to_siae.siret, email.body)
        self.assertIn(job_application.to_siae.kind, email.body)
        self.assertIn(job_application.to_siae.get_kind_display(), email.body)
        self.assertIn(job_application.to_siae.get_department_display(), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(accepted_by.get_full_name(), email.body)
        self.assertIn(accepted_by.email, email.body)
        self.assertIn(reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk]), email.body)

    def test_refuse(self):

        # When sent by authorized prescriber.
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            refusal_reason=JobApplication.REFUSAL_REASON_DID_NOT_COME
        )
        email = job_application.email_refuse
        # To.
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertIn(job_application.sender.email, email.bcc)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 1)
        # Body.
        self.assertIn(job_application.sender.first_name, email.body)
        self.assertIn(job_application.sender.last_name, email.body)
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
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
        self.assertIn(job_application.answer, email.body)

    def test_email_deliver_approval(self):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_ACCEPTED, approval=approval
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_deliver_approval(accepted_by)
        # To.
        self.assertIn(accepted_by.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(approval.user.get_full_name(), email.subject)
        self.assertIn(approval.number_with_spaces, email.body)
        self.assertIn(approval.user.last_name, email.body)
        self.assertIn(approval.user.first_name, email.body)
        self.assertIn(approval.user.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.to_siae.get_kind_display(), email.body)
        self.assertIn(job_application.to_siae.address_line_1, email.body)
        self.assertIn(job_application.to_siae.address_line_2, email.body)
        self.assertIn(job_application.to_siae.post_code, email.body)
        self.assertIn(job_application.to_siae.city, email.body)
        self.assertIn(settings.ITOU_EMAIL_CONTACT, email.body)

    def test_manually_deliver_approval(self):
        staff_member = UserFactory(is_staff=True)
        job_seeker = JobSeekerFactory(
            pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval=approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_deliver_approval(delivered_by=staff_member)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertIsNotNone(job_application.approval_number_sent_at)
        self.assertEqual(job_application.approval_manually_delivered_by, staff_member)
        self.assertIsNone(job_application.approval_manually_refused_at)
        self.assertIsNone(job_application.approval_manually_refused_by)
        self.assertEqual(len(mail.outbox), 1)

    def test_manually_refuse_approval(self):
        staff_member = UserFactory(is_staff=True)
        job_seeker = JobSeekerFactory(
            pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_refuse_approval(refused_by=staff_member)
        self.assertEqual(job_application.approval_manually_refused_by, staff_member)
        self.assertIsNotNone(job_application.approval_manually_refused_at)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertIsNone(job_application.approval_manually_delivered_by)
        self.assertIsNone(job_application.approval_number_sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_cancel(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED
        )

        cancellation_user = job_application.to_siae.active_members.first()
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        self.assertIn(cancellation_user.email, email.to)
        self.assertIn(job_application.sender.email, email.bcc)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 1)
        # Body.
        self.assertIn("annulée", email.body)
        self.assertIn(job_application.sender.first_name, email.body)
        self.assertIn(job_application.sender.last_name, email.body)
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        self.assertFalse(email.bcc)


class NewQualifiedJobAppSiaeNotificationTest(TestCase):
    def test_one_selected_job(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_application = JobApplicationFactory(to_siae=siae)

        # Add a selected job description to the application
        job_descriptions = siae.job_description_through.all()
        selected_job = job_descriptions[0]
        job_application.selected_jobs.add(selected_job)
        job_application.save()

        notification = NewQualifiedJobAppSiaeNotification(job_application=job_application)

        membership = siae.siaemembership_set.first()
        self.assertFalse(membership.notifications)
        notification.subscribe(recipient=membership)
        self.assertTrue(notification.is_subscribed(recipient=membership))

        # Receiver is now subscribed to one kind of notification
        self.assertEqual(len(notification._get_recipient_subscribed_pks(recipient=membership)), 1)

        # A job application is sent concerning another job_description.
        # He should then be subscribed to two different notifications.
        job_application = JobApplicationFactory(to_siae=siae)
        selected_job = job_descriptions[1]
        job_application.selected_jobs.add(selected_job)
        job_application.save()

        notification = NewQualifiedJobAppSiaeNotification(job_application=job_application)
        notification.subscribe(recipient=membership)
        self.assertTrue(notification.is_subscribed(recipient=membership))

        self.assertEqual(len(notification._get_recipient_subscribed_pks(recipient=membership)), 2)
        self.assertEqual(len(membership.notifications), 1)

        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 1)

    def test_multiple_selected_jobs_multiple_recipients(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_descriptions = siae.job_description_through.all()

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        notification = NewQualifiedJobAppSiaeNotification(selected_jobs_pks=[job_descriptions[0].pk])
        notification.SEND_TO_UNSET_RECIPIENTS = False  # Disable default subscription to test "manual" subscription
        notification.subscribe(membership)

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        notification = NewQualifiedJobAppSiaeNotification(selected_jobs_pks=[job_descriptions[1].pk])
        notification.SEND_TO_UNSET_RECIPIENTS = False  # Disable default subscription to test "manual" subscription
        notification.subscribe(membership)

        # Two selected jobs. Each user subscribed to one of them. We should have two recipients.
        job_application = JobApplicationFactory(to_siae=siae)
        job_application.selected_jobs.add(job_descriptions[0])
        job_application.selected_jobs.add(job_descriptions[1])
        job_application.save()

        notification = NewQualifiedJobAppSiaeNotification(job_application=job_application)
        notification.SEND_TO_UNSET_RECIPIENTS = False  # Disable default subscription to test "manual" subscription
        self.assertEqual(len(notification.recipients_emails), 2)

    def test_default_subscription(self):
        """
        Unset recipients should receive new job application notifications.
        """
        siae = SiaeWithMembershipAndJobsFactory()
        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)

        job_application = JobApplicationFactory(to_siae=siae)

        # Add a job description to the application
        selected_job = siae.job_description_through.first()
        job_application.selected_jobs.add(selected_job)
        job_application.save()

        notification = NewQualifiedJobAppSiaeNotification(job_application=job_application)

        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), siae.members.count())


class JobApplicationWorkflowTest(TestCase):
    """Test JobApplication workflow."""

    def test_accept_job_application_sent_by_job_seeker(self):
        job_seeker = JobSeekerFactory()
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_seeker.pole_emploi_id, "")

        kwargs = {"job_seeker": job_seeker, "sender": job_seeker, "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER}
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)

        self.assertEqual(job_seeker.job_applications.count(), 4)
        self.assertEqual(job_seeker.job_applications.pending().count(), 4)

        job_application = job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_PROCESSING).first()
        job_application.accept(user=job_application.to_siae.members.first())

        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count(), 1)
        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).count(), 3)

        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_job_seeker_with_valid_approval(self):
        job_seeker = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval.number, pe_approval.number)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_job_seeker_with_forgotten_pole_emploi_id(self):
        job_seeker = JobSeekerFactory(
            pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNone(job_application.approval)
        self.assertEqual(job_application.approval_delivery_mode, JobApplication.APPROVAL_DELIVERY_MODE_MANUAL)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE requis sur Itou", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_prescriber(self):
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_authorized_prescriber(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_authorized_prescriber_with_approval_in_waiting_period(self):
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertTrue(approval.is_in_waiting_period)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_prescriber_with_approval_in_waiting_period(self):
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertTrue(approval.is_in_waiting_period)
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.accept(user=job_application.to_siae.members.first())

    def test_accept_job_application_sent_by_siae(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertTrue(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour", mail.outbox[1].subject)

    def test_accept_job_application_sent_by_siae_with_no_approval(self):
        """
        A SIAE can hire somebody without getting approval if they don't want one
        Basically the same as the 'accept' part, except we don't create an approval
        and we don't notify
        """
        job_application = JobApplicationWithoutApprovalFactory(state=JobApplicationWorkflow.STATE_PROCESSING)
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertTrue(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNone(job_application.approval)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, "")
        # Check sent email (no notification of approval).
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)

    def test_accept_job_application_sent_by_siae_not_subject_to_eligibility_rules(self):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=Siae.KIND_GEIQ
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertFalse(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNone(job_application.approval)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, "")
        # Check sent email.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)

    def test_refuse(self):
        user = JobSeekerFactory()
        kwargs = {"job_seeker": user, "sender": user, "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER}

        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)

        self.assertEqual(user.job_applications.count(), 2)
        self.assertEqual(user.job_applications.pending().count(), 2)

        for job_application in user.job_applications.all():
            job_application.refuse()
            # Check sent email.
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("Candidature déclinée", mail.outbox[0].subject)
            mail.outbox = []

    def test_cancel_delete_linked_approval(self):
        job_application = JobApplicationWithApprovalFactory()
        self.assertEqual(job_application.job_seeker.approvals.count(), 1)
        self.assertEqual(JobApplication.objects.filter(approval=job_application.approval).count(), 1)

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_CANCELLED)

        job_application.refresh_from_db()
        self.assertFalse(job_application.approval)

    def test_cancel_do_not_delete_linked_approval(self):

        # The approval is linked to two accepted job applications
        job_application = JobApplicationWithApprovalFactory()
        approval = job_application.approval
        JobApplicationWithApprovalFactory(approval=approval, job_seeker=job_application.job_seeker)

        self.assertEqual(job_application.job_seeker.approvals.count(), 1)
        self.assertEqual(JobApplication.objects.filter(approval=approval).count(), 2)

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_CANCELLED)

        job_application.refresh_from_db()
        self.assertTrue(job_application.approval)

    def test_cancellation_not_allowed(self):
        today = datetime.date.today()

        # Outside cancellation delay
        job_application = JobApplicationWithApprovalFactory(hiring_start_at=(today - relativedelta(days=365)))
        cancellation_user = job_application.to_siae.active_members.first()

        # xworkflows.base.AbortTransition
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)

        # Wrong state
        job_application = JobApplicationWithApprovalFactory(
            hiring_start_at=today, state=JobApplicationWorkflow.STATE_NEW
        )
        cancellation_user = job_application.to_siae.active_members.first()
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)
