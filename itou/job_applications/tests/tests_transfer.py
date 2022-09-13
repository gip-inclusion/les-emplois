from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentBySiaeFactory,
    JobApplicationWithEligibilityDiagnosis,
)
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory, SiaeWith2MembershipsFactory
from itou.users.factories import UserFactory


class JobApplicationTransferModelTest(TestCase):
    def test_is_in_transferable_state(self):
        # If job application is in NEW or ACCEPTED state
        # it can't be transfered
        evil_states = [JobApplicationWorkflow.STATE_NEW, JobApplicationWorkflow.STATE_ACCEPTED]
        good_states = [
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

        for evil_state in evil_states:
            with self.subTest(evil_state):
                job_application = JobApplicationFactory(state=evil_state)
                self.assertFalse(job_application.is_in_transferable_state)

        for good_state in good_states:
            with self.subTest(good_state):
                job_application = JobApplicationFactory(state=good_state)
                self.assertTrue(job_application.is_in_transferable_state)

    def test_can_be_transferred(self):
        # Only users in both origin and target SIAE
        # can transfer a job_application
        # (provided it is in correct state)
        origin_siae = SiaeFactory(with_membership=True)
        target_siae = SiaeFactory(with_membership=True)

        origin_user = origin_siae.members.first()
        target_user = target_siae.members.first()
        lambda_user = UserFactory(is_siae_staff=False)
        target_siae.members.add(origin_user)

        job_application = JobApplicationFactory(to_siae=origin_siae)

        self.assertTrue(origin_user.is_siae_staff)
        self.assertTrue(target_user.is_siae_staff)
        self.assertFalse(job_application.can_be_transferred(target_user, job_application.to_siae))
        self.assertFalse(job_application.can_be_transferred(lambda_user, target_siae))
        self.assertFalse(job_application.can_be_transferred(target_user, target_siae))
        self.assertFalse(job_application.can_be_transferred(origin_user, target_siae))

        job_application.state = JobApplicationWorkflow.STATE_PROCESSING

        self.assertTrue(job_application.can_be_transferred(origin_user, target_siae))

    def test_transfer_to(self):
        # If all conditions are valid, a user can transfer job applications between SIAE they are member of,
        # provided job application is in an acceptable state.
        # After transfer:
        # - job application is not linked to origin SIAE anymore (only to target SIAE)
        # - eligibility diagnosis is deleted if not created by an authorized prescriber
        origin_siae = SiaeFactory(with_membership=True)
        target_siae = SiaeFactory(with_membership=True)

        origin_user = origin_siae.members.first()
        target_user = target_siae.members.first()
        lambda_user = UserFactory(is_siae_staff=False)
        target_siae.members.add(origin_user)

        job_application = JobApplicationWithEligibilityDiagnosis(to_siae=origin_siae)

        # Conditions hould be covered by previous test, but does not hurt (and tests raise)
        with self.assertRaises(ValidationError):
            job_application.transfer_to(lambda_user, target_siae)
        with self.assertRaises(ValidationError):
            job_application.transfer_to(origin_user, origin_siae)
        with self.assertRaises(ValidationError):
            job_application.transfer_to(target_user, target_siae)
        with self.assertRaises(ValidationError):
            job_application.transfer_to(origin_user, target_siae)

        job_application.state = JobApplicationWorkflow.STATE_PROCESSING
        job_application.transfer_to(origin_user, target_siae)
        job_application.refresh_from_db()

        # "Normal" transfer
        self.assertEqual(job_application.to_siae, target_siae)
        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_NEW)
        self.assertIsNotNone(job_application.eligibility_diagnosis)

        # Eligibilty diagnosis not sent by authorized prescriber must be deleted
        job_application = JobApplicationSentBySiaeFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=origin_siae,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        eligibility_diagnosis_pk = job_application.eligibility_diagnosis.pk
        job_application.transfer_to(origin_user, target_siae)
        job_application.refresh_from_db()

        self.assertEqual(job_application.to_siae, target_siae)
        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_NEW)
        self.assertIsNone(job_application.eligibility_diagnosis)
        self.assertFalse(EligibilityDiagnosis.objects.filter(pk=eligibility_diagnosis_pk))

    def test_model_fields(self):
        # Check new fields in model
        origin_siae = SiaeFactory(with_membership=True)
        target_siae = SiaeFactory(with_membership=True)

        origin_user = origin_siae.members.first()
        target_user = target_siae.members.first()
        target_siae.members.add(origin_user)

        job_application = JobApplicationSentBySiaeFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=origin_siae,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
            answer="Answer to job seeker",
            answer_to_prescriber="Answer to prescriber",
        )

        # Failing to transfer must not update new fields
        with self.assertRaises(ValidationError):
            job_application.transfer_to(target_user, target_siae)
        self.assertIsNone(job_application.transferred_by)
        self.assertIsNone(job_application.transferred_from)
        self.assertIsNone(job_application.transferred_at)

        with self.assertNumQueries(7):
            job_application.transfer_to(origin_user, target_siae)

        job_application.refresh_from_db()

        self.assertEqual(job_application.transferred_by, origin_user)
        self.assertEqual(job_application.transferred_from, origin_siae)
        self.assertEqual(timezone.localdate(), job_application.transferred_at.date())
        self.assertEqual(job_application.to_siae, target_siae)
        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_NEW)
        self.assertIsNone(job_application.eligibility_diagnosis)
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.answer_to_prescriber, "")

    def test_workflow_transitions(self):
        # `source` contains possible entry points of transition
        for from_state in JobApplicationWorkflow.transitions["transfer"].source:
            with self.subTest(from_state):
                job_application = JobApplicationSentBySiaeFactory(state=from_state)
                job_application.state = JobApplicationWorkflow.STATE_NEW
                job_application.save()  # Triggers transition check

    def test_transfer_must_notify_siae_and_job_seeker(self):
        # Send email notification of transfer to :
        # - origin SIAE
        # - job seeker
        # - Prescriber (if any linked eligibility diagnosis was not sent by a SIAE)
        origin_siae = SiaeFactory(with_membership=True)
        target_siae = SiaeFactory(with_membership=True)

        origin_user = origin_siae.members.first()
        target_siae.members.add(origin_user)

        job_application = JobApplicationSentBySiaeFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=origin_siae,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user, target_siae)

        # Eligigibility diagnosis is done by SIAE : must not send an email
        self.assertEqual(len(mail.outbox), 2)

        self.assertEqual(len(mail.outbox[0].to), 1)
        self.assertIn(origin_user.email, mail.outbox[0].to)
        self.assertIn(
            f"La candidature de {job_seeker.first_name} {job_seeker.last_name} a été transférée",
            mail.outbox[0].subject,
        )
        self.assertIn("a transféré la candidature de :", mail.outbox[0].body)

        self.assertEqual(len(mail.outbox[1].to), 1)
        self.assertIn(job_application.job_seeker.email, mail.outbox[1].to)
        self.assertIn("Votre candidature a été transférée à une autre structure", mail.outbox[1].subject)
        self.assertIn("a transféré votre candidature à la structure", mail.outbox[1].body)

    def test_transfer_must_notify_prescriber(self):
        # Same test and conditions as above, but this time prescriber
        # at the origin of the eligibility disgnosis must be notified
        origin_siae = SiaeFactory(with_membership=True)
        target_siae = SiaeFactory(with_membership=True)

        origin_user = origin_siae.members.first()
        target_siae.members.add(origin_user)

        # Eligibility diagnosis was made by a prescriber
        job_application = JobApplicationSentByPrescriberFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=origin_siae,
            eligibility_diagnosis=EligibilityDiagnosisFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user, target_siae)

        self.assertEqual(len(mail.outbox), 3)

        # Other email content have been checked in previous test
        # Focusing on prescriber email content
        self.assertEqual(len(mail.outbox[2].to), 1)
        self.assertIn(job_application.sender.email, mail.outbox[2].to)
        self.assertIn(
            f"La candidature de {job_seeker.first_name} {job_seeker.last_name} a été transférée",
            mail.outbox[2].subject,
        )
        self.assertIn("a transféré la candidature de :", mail.outbox[2].body)

    def test_transfer_notifications_to_many_siae_members(self):
        # Same as test_transfer_must_notify_siae_and_job_seeker
        # but with to recipients for SIAE transfer notification
        origin_siae = SiaeWith2MembershipsFactory()
        target_siae = SiaeFactory(with_membership=True)

        origin_user_1 = origin_siae.members.all()[0]
        origin_user_2 = origin_siae.members.all()[1]
        target_siae.members.add(origin_user_1)

        job_application = JobApplicationSentBySiaeFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae=origin_siae,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user_1, target_siae)

        # Only checking SIAE email
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(len(mail.outbox[0].to), 2)
        self.assertIn(origin_user_1.email, mail.outbox[0].to)
        self.assertIn(origin_user_2.email, mail.outbox[0].to)
        self.assertIn(
            f"La candidature de {job_seeker.first_name} {job_seeker.last_name} a été transférée",
            mail.outbox[0].subject,
        )
        self.assertIn("a transféré la candidature de :", mail.outbox[0].body)
