import datetime

from django.core.management import call_command
from django.test import TestCase

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithEligibilityDiagnosis,
)
from itou.job_applications.models import JobApplication
from itou.users.models import User


class ManagementCommandsTest(TestCase):
    """
    Test the deduplication of several users.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.
    """

    def test_deduplicate_job_seekers(self):
        """
        Easy case : among all the duplicates, only one has a PASS IAE.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationWithApprovalFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertIsNone(user1.nir)
        self.assertEqual(1, user1.approvals.count())
        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(1, user1.eligibility_diagnoses.count())

        # Create `user2`.
        job_app2 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertIsNone(user2.nir)
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(1, user2.eligibility_diagnoses.count())

        # Create `user3`.
        job_app3 = JobApplicationWithEligibilityDiagnosis(**kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.nir

        self.assertIsNotNone(user3.nir)
        self.assertEqual(0, user3.approvals.count())
        self.assertEqual(1, user3.job_applications.count())
        self.assertEqual(1, user3.eligibility_diagnoses.count())

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        self.assertEqual(user1.nir, expected_nir)

        self.assertEqual(3, user1.job_applications.count())
        self.assertEqual(3, user1.eligibility_diagnoses.count())
        self.assertEqual(1, user1.approvals.count())

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())

    def test_deduplicate_job_seekers_without_empty_sender_field(self):
        """
        Easy case: among all the duplicates, only one has a PASS IAE.
        Ensure that the `sender` field is never left empty.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1` through a job application sent by him.
        job_app1 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(job_app1.sender, user1)

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(job_app2.sender, user2)

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user3 = job_app3.job_seeker
        self.assertNotEqual(job_app3.sender, user3)
        job_app3_sender = job_app3.sender  # The sender is a prescriber.

        # Ensure that `user1` will always be the target into which duplicates will be merged
        # by attaching a PASS IAE to him.
        self.assertEqual(0, user1.approvals.count())
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(0, user3.approvals.count())
        ApprovalFactory(user=user1)

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        self.assertEqual(3, user1.job_applications.count())

        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        job_app3.refresh_from_db()

        self.assertEqual(job_app1.sender, user1)
        self.assertEqual(job_app2.sender, user1)  # The sender must now be user1.
        self.assertEqual(job_app3.sender, job_app3_sender)  # The sender must still be a prescriber.

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())
