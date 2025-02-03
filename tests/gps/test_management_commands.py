from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from django.core import management

from itou.gps.management.commands import sync_follow_up_groups_and_members
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership, FranceTravailContact
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    PrescriberFactory,
)


class TestSyncGroupsManagementCommand:
    @pytest.fixture(autouse=True)
    def setup(self, settings):
        # To be able to use assertCountEqual
        settings.GPS_GROUPS_CREATED_BY_EMAIL = "rocking@developer.com"
        ItouStaffFactory(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)

    def test_get_uses_contacts(ids):
        beneficiary = JobSeekerFactory()

        # employer with multiple contacts
        employer = EmployerFactory()
        # A job app sent by the employer (we don't check if it's sent to the employer company or another)
        job_app_1 = JobApplicationFactory(
            job_seeker=beneficiary,
            sender=employer,
            sender_kind=UserKind.EMPLOYER,
            sender_company=CompanyFactory(),
            eligibility_diagnosis=None,
        )
        geiq_diag_1 = GEIQEligibilityDiagnosisFactory(
            job_seeker=beneficiary,
            author=employer,
            from_geiq=True,
        )
        iae_diag_1 = IAEEligibilityDiagnosisFactory(
            job_seeker=beneficiary,
            author=employer,
            from_employer=True,
        )
        for state in JobApplicationState:
            JobApplicationTransitionLog.objects.create(user=employer, to_state=state, job_application=job_app_1)
        job_app_1_log = JobApplicationTransitionLog.objects.get(to_state=JobApplicationState.ACCEPTED)

        # this prescriber had multiple "contacts":
        prescriber = PrescriberFactory()
        job_app_2 = JobApplicationFactory(
            job_seeker=beneficiary,
            sender=prescriber,
            sent_by_authorized_prescriber_organisation=True,
            eligibility_diagnosis=None,
        )
        geiq_diag_2 = GEIQEligibilityDiagnosisFactory(
            job_seeker=beneficiary,
            author=prescriber,
            from_prescriber=True,
        )
        iae_diag_2 = IAEEligibilityDiagnosisFactory(
            job_seeker=beneficiary,
            author=prescriber,
            from_prescriber=True,
        )

        # non authorized prescriber sent job application are ignored
        JobApplicationFactory(
            job_seeker=beneficiary,
            eligibility_diagnosis=None,
        )

        # self sent job application are ignored
        JobApplicationFactory(
            job_seeker=beneficiary,
            sender=beneficiary,
            eligibility_diagnosis=None,
        )

        assert sync_follow_up_groups_and_members.get_users_contacts([beneficiary.pk]) == {
            beneficiary.pk: {
                employer.pk: sorted(
                    [
                        job_app_1.created_at,
                        geiq_diag_1.created_at,
                        iae_diag_1.created_at,
                        job_app_1_log.timestamp,
                    ]
                ),
                prescriber.pk: sorted(
                    [
                        job_app_2.created_at,
                        geiq_diag_2.created_at,
                        iae_diag_2.created_at,
                    ]
                ),
            },
        }

    def test_sync_groups(self, settings):
        batch_group_creator = ItouStaffFactory()
        settings.GPS_GROUPS_CREATED_BY_EMAIL = batch_group_creator.email

        follower_1 = PrescriberFactory()
        follower_2 = PrescriberFactory()

        # A beneficiary with no existing group
        beneficiary_1 = JobSeekerFactory()
        # Another one with a group but we found new contacts
        beneficiary_2 = JobSeekerFactory()
        group_2 = FollowUpGroupFactory(beneficiary=beneficiary_2)
        membership_2_1 = FollowUpGroupMembershipFactory(
            follow_up_group=group_2,
            member=follower_1,
            is_referent=True,
            created_in_bulk=False,
            creator=follower_2,
        )
        membership_2_1_created_at = membership_2_1.created_at

        # Simple contacts with only sent job application
        JobApplicationFactory(
            sender=follower_1,
            job_seeker=beneficiary_1,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )
        JobApplicationFactory(
            sender=follower_1,
            job_seeker=beneficiary_1,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )
        JobApplicationFactory(
            sender=follower_1,
            job_seeker=beneficiary_2,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )
        JobApplicationFactory(
            sender=follower_1,
            job_seeker=beneficiary_2,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )
        JobApplicationFactory(
            sender=follower_2,
            job_seeker=beneficiary_2,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )
        JobApplicationFactory(
            sender=follower_2,
            job_seeker=beneficiary_2,
            eligibility_diagnosis=None,
            sent_by_authorized_prescriber_organisation=True,
        )

        contacts_data = sync_follow_up_groups_and_members.get_users_contacts([beneficiary_1.pk, beneficiary_2.pk])
        management.call_command("sync_follow_up_groups_and_members", wet_run=True)

        # New group and membership for beneficiary_1
        group_1 = FollowUpGroup.objects.get(beneficiary=beneficiary_1)
        assert group_1.created_in_bulk
        membership_1_1 = FollowUpGroupMembership.objects.get(follow_up_group=group_1)
        assert membership_1_1.member == follower_1
        assert not membership_1_1.is_referent
        assert membership_1_1.created_in_bulk
        assert membership_1_1.creator == batch_group_creator
        assert membership_1_1.last_contact_at == contacts_data[beneficiary_1.pk][follower_1.pk][1]
        assert membership_1_1.created_at == contacts_data[beneficiary_1.pk][follower_1.pk][0]

        # group already existed for beneficiary_2
        membership_2_1.refresh_from_db()
        # Update membership for follower_1
        assert membership_2_1.is_referent  # didn't change
        assert not membership_2_1.created_in_bulk  # didn't change
        assert membership_2_1.creator == follower_2  # didin't change
        assert membership_2_1.created_at == membership_2_1_created_at
        assert membership_2_1.last_contact_at == contacts_data[beneficiary_2.pk][follower_1.pk][1]
        # create the one for follower_2
        membership_2_2 = FollowUpGroupMembership.objects.get(follow_up_group=group_2, member=follower_2)
        assert membership_2_2.member == follower_2
        assert not membership_2_2.is_referent
        assert membership_2_2.created_in_bulk
        assert membership_2_2.creator == batch_group_creator
        assert membership_2_2.last_contact_at == contacts_data[beneficiary_2.pk][follower_2.pk][1]
        assert membership_2_2.created_at == contacts_data[beneficiary_2.pk][follower_2.pk][0]


class TestImportAdvisorManagementCommand:
    def test_import_advisor_information(self):
        contacted_profile = JobSeekerProfileFactory(with_contact=True)
        contactless_profile = JobSeekerProfileFactory()
        profile_contact_no_name = JobSeekerProfileFactory()
        profile_contact_no_email = JobSeekerProfileFactory()

        # dataset contains a the existing groups

        mocked_pandas_dataset = pd.DataFrame(
            {
                "nir": [
                    contacted_profile.nir,
                    contactless_profile.nir,
                    "123456789010101",  # non-existent in the database,
                    contacted_profile.nir,  # duplicate - ignored with a log
                    profile_contact_no_name.nir,
                    profile_contact_no_email.nir,
                ],
                "prescriber_name": [
                    "Test MacTest",
                    "Test Testson",
                    "Test Ignored",
                    "Test Ignored",
                    np.nan,
                    "Test Ignored",
                ],
                "prescriber_email": [
                    "test.mactest@francetravail.fr",
                    "test.testson@francetravail.fr",
                    "testignored@francetravail.fr",
                    "testignored@francetravail.fr",
                    "testignored@francetravail.fr",
                    np.nan,
                ],
            }
        )

        with patch("pandas.read_excel", return_value=mocked_pandas_dataset):
            management.call_command("import_advisor_information", "example.xlsx", wet_run=True)

        assert FranceTravailContact.objects.count() == 2
        assert JobSeekerProfile.objects.filter(advisor_information__isnull=True).count() == 2

        contacted_profile.refresh_from_db()
        assert contacted_profile.advisor_information.name == "Test MacTest"
        assert contacted_profile.advisor_information.email == "test.mactest@francetravail.fr"

        contactless_profile.refresh_from_db()
        assert contactless_profile.advisor_information.name == "Test Testson"
        assert contactless_profile.advisor_information.email == "test.testson@francetravail.fr"

    def test_import_advisor_information_recover_keyless_nir(self):
        # test asserts that the command can recover from missing a key in the NIR value
        profile = JobSeekerProfileFactory(with_contact=True)

        mocked_pandas_dataset = pd.DataFrame(
            {
                "nir": [profile.nir[:13]],
                "prescriber_name": ["Test MacTest"],
                "prescriber_email": ["test.mactest@francetravail.fr"],
            }
        )
        print(str(profile.nir[:13]))

        with patch("pandas.read_excel", return_value=mocked_pandas_dataset):
            management.call_command("import_advisor_information", "example.xlsx", wet_run=True)

        profile.refresh_from_db()
        assert profile.advisor_information.name == "Test MacTest"
        assert profile.advisor_information.email == "test.mactest@francetravail.fr"
