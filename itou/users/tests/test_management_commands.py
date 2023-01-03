import datetime
import io
import os
import unittest

from django.contrib.auth.models import Group
from django.core.management import call_command

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplication
from itou.users.models import User
from itou.utils.test import TestCase


@unittest.skipUnless(os.getenv("CI", False), "It is a long management command and normally not subject to change!")
class DeduplicateJobSeekersManagementCommandsTest(TestCase):
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
        job_app1 = JobApplicationFactory(with_approval=True, job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        assert user1.nir is None
        assert 1 == user1.approvals.count()
        assert 1 == user1.job_applications.count()
        assert 1 == user1.eligibility_diagnoses.count()

        # Create `user2`.
        job_app2 = JobApplicationFactory(with_eligibility_diagnosis=True, job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        assert user2.nir is None
        assert 0 == user2.approvals.count()
        assert 1 == user2.job_applications.count()
        assert 1 == user2.eligibility_diagnoses.count()

        # Create `user3`.
        job_app3 = JobApplicationFactory(with_eligibility_diagnosis=True, **kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.nir

        assert user3.nir is not None
        assert 0 == user3.approvals.count()
        assert 1 == user3.job_applications.count()
        assert 1 == user3.eligibility_diagnoses.count()

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True, wet_run=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        assert user1.nir == expected_nir

        assert 3 == user1.job_applications.count()
        assert 3 == user1.eligibility_diagnoses.count()
        assert 1 == user1.approvals.count()

        assert 0 == User.objects.filter(email=user2.email).count()
        assert 0 == User.objects.filter(email=user3.email).count()

        assert 0 == JobApplication.objects.filter(job_seeker=user2).count()
        assert 0 == JobApplication.objects.filter(job_seeker=user3).count()

        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user2).count()
        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user3).count()

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

        assert 1 == user1.job_applications.count()
        assert job_app1.sender == user1

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        assert 1 == user2.job_applications.count()
        assert job_app2.sender == user2

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationFactory(with_eligibility_diagnosis=True, job_seeker__nir=None, **kwargs)
        user3 = job_app3.job_seeker
        assert job_app3.sender != user3
        job_app3_sender = job_app3.sender  # The sender is a prescriber.

        # Ensure that `user1` will always be the target into which duplicates will be merged
        # by attaching a PASS IAE to him.
        assert 0 == user1.approvals.count()
        assert 0 == user2.approvals.count()
        assert 0 == user3.approvals.count()
        ApprovalFactory(user=user1)

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True, wet_run=True)

        assert 3 == user1.job_applications.count()

        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        job_app3.refresh_from_db()

        assert job_app1.sender == user1
        assert job_app2.sender == user1  # The sender must now be user1.
        assert job_app3.sender == job_app3_sender  # The sender must still be a prescriber.

        assert 0 == User.objects.filter(email=user2.email).count()
        assert 0 == User.objects.filter(email=user3.email).count()

        assert 0 == JobApplication.objects.filter(job_seeker=user2).count()
        assert 0 == JobApplication.objects.filter(job_seeker=user3).count()

        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user2).count()
        assert 0 == EligibilityDiagnosis.objects.filter(job_seeker=user3).count()


class TestSyncPermsTestCase(TestCase):
    def test_sync_perms(self):
        stdout = io.StringIO()
        call_command("sync_group_and_perms", stdout=stdout)
        stdout.seek(0)
        output = stdout.readlines()
        assert output == [
            "group name=itou-admin created\n",
            "group name=itou-support-externe created\n",
            "All done!\n",
        ]
        assert Group.objects.all().count() == 2
        admin_group = Group.objects.all()[0]
        assert admin_group.name == "itou-admin"
        assert [perm.codename for perm in admin_group.permissions.all()] == [
            "add_emailaddress",
            "change_emailaddress",
            "view_emailaddress",
            "view_datum",
            "add_approval",
            "change_approval",
            "delete_approval",
            "view_approval",
            "view_poleemploiapproval",
            "add_prolongation",
            "change_prolongation",
            "delete_prolongation",
            "view_prolongation",
            "add_suspension",
            "change_suspension",
            "delete_suspension",
            "view_suspension",
            "view_commune",
            "view_country",
            "view_department",
            "view_city",
            "view_administrativecriteria",
            "add_eligibilitydiagnosis",
            "change_eligibilitydiagnosis",
            "view_eligibilitydiagnosis",
            "add_selectedadministrativecriteria",
            "change_selectedadministrativecriteria",
            "delete_selectedadministrativecriteria",
            "view_selectedadministrativecriteria",
            "change_employeerecord",
            "delete_employeerecord",
            "view_employeerecord",
            "add_institution",
            "change_institution",
            "view_institution",
            "add_institutionmembership",
            "change_institutionmembership",
            "delete_institutionmembership",
            "view_institutionmembership",
            "change_laborinspectorinvitation",
            "delete_laborinspectorinvitation",
            "view_laborinspectorinvitation",
            "change_prescriberwithorginvitation",
            "delete_prescriberwithorginvitation",
            "view_prescriberwithorginvitation",
            "change_siaestaffinvitation",
            "delete_siaestaffinvitation",
            "view_siaestaffinvitation",
            "change_jobapplication",
            "delete_jobapplication",
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            "view_appellation",
            "view_rome",
            "add_prescribermembership",
            "change_prescribermembership",
            "delete_prescribermembership",
            "view_prescribermembership",
            "add_prescriberorganization",
            "change_prescriberorganization",
            "view_prescriberorganization",
            "view_evaluatedadministrativecriteria",
            "view_evaluatedjobapplication",
            "view_evaluatedsiae",
            "view_evaluationcampaign",
            "add_siae",
            "change_siae",
            "view_siae",
            "change_siaeconvention",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "add_siaejobdescription",
            "change_siaejobdescription",
            "delete_siaejobdescription",
            "view_siaejobdescription",
            "add_siaemembership",
            "change_siaemembership",
            "delete_siaemembership",
            "view_siaemembership",
            "change_jobseekerprofile",
            "view_jobseekerprofile",
            "add_user",
            "change_user",
            "view_user",
        ]
        support_group = Group.objects.all()[1]
        assert support_group.name == "itou-support-externe"
        assert [perm.codename for perm in support_group.permissions.all()] == [
            "view_emailaddress",
            "view_approval",
            "view_poleemploiapproval",
            "view_prolongation",
            "view_suspension",
            "view_commune",
            "view_country",
            "view_department",
            "view_city",
            "view_administrativecriteria",
            "view_eligibilitydiagnosis",
            "view_selectedadministrativecriteria",
            "view_employeerecord",
            "view_institution",
            "view_institutionmembership",
            "view_laborinspectorinvitation",
            "view_prescriberwithorginvitation",
            "view_siaestaffinvitation",
            "view_jobapplication",
            "view_jobapplicationtransitionlog",
            "view_appellation",
            "view_rome",
            "view_prescribermembership",
            "view_prescriberorganization",
            "view_siae",
            "view_siaeconvention",
            "view_siaefinancialannex",
            "view_siaejobdescription",
            "view_siaemembership",
            "view_jobseekerprofile",
            "view_user",
        ]
