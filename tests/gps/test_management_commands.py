import datetime
import os
from tempfile import NamedTemporaryFile

import openpyxl
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core import management
from django.utils import timezone
from freezegun import freeze_time

from itou.gps.management.commands import sync_follow_up_groups_and_members
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.export import generate_excel_sheet
from itou.utils.models import PkSupportRemark
from itou.www.gps.enums import EndReason
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


class TestSyncGroupsManagementCommand:
    @pytest.fixture(autouse=True)
    def setup(self, settings):
        # To be able to use assertCountEqual
        settings.GPS_GROUPS_CREATED_BY_EMAIL = "rocking@developer.com"
        ItouStaffFactory(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)

    def test_get_users_contacts(ids):
        beneficiary = JobSeekerFactory()
        staff = ItouStaffFactory()

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
            from_employer=True,
        )
        iae_diag_1 = IAEEligibilityDiagnosisFactory(
            job_seeker=beneficiary,
            author=employer,
            from_employer=True,
        )
        for state in JobApplicationState:
            JobApplicationTransitionLog.objects.create(user=employer, to_state=state, job_application=job_app_1)
        job_app_1_log = JobApplicationTransitionLog.objects.get(to_state=JobApplicationState.ACCEPTED)
        # ignored transition created by a staff member
        JobApplicationTransitionLog.objects.create(
            user=staff, to_state=JobApplicationState.ACCEPTED, job_application=job_app_1
        )

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
        non_authorized_prescriber = PrescriberFactory()
        job_app_3 = JobApplicationFactory(
            job_seeker=beneficiary,
            sender=non_authorized_prescriber,
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
                non_authorized_prescriber.pk: [job_app_3.created_at],
            },
        }

    def test_sync_groups(self, settings):
        batch_group_creator = ItouStaffFactory()
        settings.GPS_GROUPS_CREATED_BY_EMAIL = batch_group_creator.email

        follower_1 = PrescriberFactory()
        follower_2 = PrescriberFactory()

        staff = ItouStaffFactory()

        # A beneficiary with no existing group, staff user will be ignored
        beneficiary_1 = JobSeekerFactory(created_by=staff)
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
        )
        JobApplicationFactory(
            sender=follower_1,
            job_seeker=beneficiary_1,
            eligibility_diagnosis=None,
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

        # simple contact with created job seeker
        beneficiary_3 = JobSeekerFactory(created_by=follower_1)

        contacts_data = sync_follow_up_groups_and_members.get_users_contacts(
            [beneficiary_1.pk, beneficiary_2.pk, beneficiary_3.pk]
        )
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

        # New group and membership for beneficiary_3
        group_3 = FollowUpGroup.objects.get(beneficiary=beneficiary_3)
        assert group_3.created_in_bulk
        membership_3_1 = FollowUpGroupMembership.objects.get(follow_up_group=group_3)
        assert membership_3_1.member == follower_1
        assert not membership_3_1.is_referent
        assert membership_3_1.created_in_bulk
        assert membership_3_1.creator == batch_group_creator
        assert membership_3_1.last_contact_at == beneficiary_3.date_joined
        assert membership_3_1.created_at == beneficiary_3.date_joined


@freeze_time()
def test_import_advisor_information(settings, caplog, mocker):
    batch_group_creator = ItouStaffFactory()
    settings.GPS_GROUPS_CREATED_BY_EMAIL = batch_group_creator.email

    job_seeker_with_no_correct_data = JobSeekerFactory()
    employer = EmployerFactory()

    unknown_safir = "22222"
    known_safir = "11111"
    organization = PrescriberOrganizationFactory(code_safir_pole_emploi=known_safir)

    # A job seeker whose advisor is a prescriber that already exists, with no follow up group
    job_seeker_1 = JobSeekerFactory()
    prescriber_1 = PrescriberFactory()

    # A job seeker whose advisor is a prescriber that already exists, with a follow up group
    job_seeker_2 = JobSeekerFactory()
    prescriber_2 = PrescriberFactory()
    membership_2 = FollowUpGroupMembershipFactory(
        follow_up_group__beneficiary=job_seeker_2,
        member=prescriber_2,
        ended_at=datetime.date(2000, 1, 1),
        end_reason="The millennium bug",
        last_contact_at=datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
        is_active=False,
    )

    # A job seeker whose advisor is a prescriber that does not exist, with a safir that exists
    job_seeker_3 = JobSeekerFactory()
    # previous certified referent
    previous_membership_3 = FollowUpGroupMembershipFactory(
        follow_up_group__beneficiary=job_seeker_3, is_referent_certified=True
    )

    # A job seeker whose advisor is a prescriber that does not exist, with a safir that does not exist
    job_seeker_4 = JobSeekerFactory()

    # An old membership that had is_referent_certified=True
    old_certified_referent_membership = FollowUpGroupMembershipFactory(is_referent_certified=True)

    with NamedTemporaryFile() as file:
        # write imported file add a column to ignore to ensure the code does'nt crash
        headers = ["ID", "prenom_cdde", "nom_cdde", "code_safir_agence", "mail_cdde", "some random column"]
        data = [
            # missing prenom_cdde
            [job_seeker_with_no_correct_data.pk, "", "Test", "Test", "Test", "random value"],
            # missing nom_cdde
            [job_seeker_with_no_correct_data.pk, "Test", "", "Test", "Test", "random value"],
            # missing code_safir_agence
            [job_seeker_with_no_correct_data.pk, "test", "Test", "", "Test", "random value"],
            # missing mail_cdde
            [job_seeker_with_no_correct_data.pk, "test", "Test", "Test", "", "random value"],
            # mail_cdde is used by an employer
            [job_seeker_with_no_correct_data.pk, "Test", "Test", "Test", employer.email, "random value"],
            # Not a job seeker
            [prescriber_1.pk, "Test", "Test", "Test", "Test", "random value"],
            # correct data
            [
                job_seeker_1.pk,
                "prescriber_1_first_name",  # This value isn't used
                "prescriber_1_last_name",  # This value isn't used
                known_safir,  # This will be ignored as the prescriber already exists
                prescriber_1.email,
                "random value",
            ],
            [
                job_seeker_2.pk,
                "prescriber_2_first_name",  # This value isn't used
                "prescriber_2_last_name",  # This value isn't used
                unknown_safir,  # This will be ignored as the prescriber already exists
                prescriber_2.email,
                "random value",
            ],
            [
                job_seeker_3.pk,
                "Alphonse",
                "Armani",
                known_safir,
                "alphonse.armani@mailinator.com",
                "random value",
            ],
            [
                job_seeker_4.pk,
                "Beatrice",
                "Balladur",
                unknown_safir,
                "beatrice.balladur@mailinator.com",
                "random value",
            ],
        ]
        generate_excel_sheet(headers, data).save(file)
        file.seek(0)
        management.call_command("import_advisor_information", file.name, wet_run=True)

    # The old membership is not certified anymore
    old_certified_referent_membership.refresh_from_db()
    assert old_certified_referent_membership.is_referent_certified is False

    # job seeker 1 to 4 groups and the one from old_certified_referent_membership
    assert FollowUpGroup.objects.count() == 5
    # each group only has one membership except for job_seeker_3's group
    assert FollowUpGroupMembership.objects.count() == 6

    # Job seeker 1:
    membership_1 = FollowUpGroupMembership.objects.get(follow_up_group__beneficiary=job_seeker_1)
    assert membership_1.is_referent_certified is True
    assert membership_1.member == prescriber_1
    # We don't attach an existing prescriber to an organisation
    assert not prescriber_1.prescribermembership_set.exists()

    # Job seeker 2:
    membership_2.refresh_from_db()
    assert membership_2.is_referent_certified is True
    assert membership_2.member == prescriber_2
    assert membership_2.ended_at is None
    assert membership_2.end_reason is None
    assert membership_2.last_contact_at == timezone.now()
    assert membership_2.is_active is True

    # Job seeker 3:
    membership_3 = (
        FollowUpGroupMembership.objects.filter(follow_up_group__beneficiary=job_seeker_3)
        .exclude(pk=previous_membership_3.pk)
        .get()
    )
    assert membership_3.is_referent_certified is True
    previous_membership_3.refresh_from_db()
    assert previous_membership_3.is_referent_certified is False
    # created prescriber
    prescriber_3 = membership_3.member
    assert prescriber_3.email == "alphonse.armani@mailinator.com"
    assert prescriber_3.first_name == "Alphonse"
    assert prescriber_3.last_name == "Armani"
    assert prescriber_3.is_prescriber
    assert prescriber_3.prescribermembership_set.get().organization == organization
    user_content_type = ContentType.objects.get_for_model(User)
    user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=prescriber_3.pk).get()
    assert user_remark.remark == "Créé par l'import des référents FT pour GPS"

    # Job seeker 4:
    membership_4 = FollowUpGroupMembership.objects.get(follow_up_group__beneficiary=job_seeker_4)
    assert membership_4.is_referent_certified is True
    # created prescriber
    prescriber_4 = membership_4.member
    assert prescriber_4.email == "beatrice.balladur@mailinator.com"
    assert prescriber_4.first_name == "Beatrice"
    assert prescriber_4.last_name == "Balladur"
    assert prescriber_4.is_prescriber
    assert not prescriber_4.prescribermembership_set.exists()
    user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=prescriber_4.pk).get()
    assert user_remark.remark == "Créé par l'import des référents FT pour GPS"

    assert caplog.messages[:-1] == [
        "Found 6 rows from GPS export.",  # 10 minus the 4 with missing data
        f"Some job seekers ids where not found: [{prescriber_1.pk}].",
        f"Some advisor email are attached to non prescriber accounts: ['{employer.email}'].",
        "Matched 4 users in the database",
        "100.00%",
        "--------------------------------------------------------------------------------",
        "Import complete. 2 prescribers were created and 4 certified referent were set.",
    ]


class TestArchiveOldFollowUpMembershipCommand:
    @freeze_time("2025-03-25")
    def test_command(self):
        old_membership = FollowUpGroupMembershipFactory(
            last_contact_at=datetime.datetime(2023, 3, 24, tzinfo=datetime.UTC)
        )
        active_membership = FollowUpGroupMembershipFactory()
        old_ended_at = datetime.date(2024, 1, 1)
        ended_membership = FollowUpGroupMembershipFactory(
            ended_at=old_ended_at,
            end_reason=EndReason.MANUAL,
        )
        management.call_command("archive_old_gps_memberships")

        old_membership.refresh_from_db()
        assert old_membership.ended_at == datetime.date(2025, 3, 25)
        assert old_membership.end_reason == EndReason.AUTOMATIC

        active_membership.refresh_from_db()
        assert active_membership.ended_at is None
        assert active_membership.end_reason is None

        ended_membership.refresh_from_db()
        assert ended_membership.ended_at == old_ended_at
        assert ended_membership.end_reason == EndReason.MANUAL


@freeze_time("2025-04-03 09:44")
def test_export_beneficiaries_for_advisor_command(tmp_path, settings):
    settings.EXPORT_DIR = tmp_path
    # Not a job seeker
    PrescriberFactory(post_code="30000")

    # Not in the correct department
    JobSeekerFactory(post_code="40000")

    job_seeker_1 = JobSeekerFactory(
        post_code="30000",
        birthdate=datetime.date(2000, 12, 31),
        nir="",
    )
    job_seeker_2 = JobSeekerFactory(
        post_code="30000",
        birthdate=None,
    )

    management.call_command("export_beneficiaries_for_advisor", "30")

    path = os.path.join(settings.EXPORT_DIR, "gps_dpt_30_2025-04-03_11:44.xlsx")
    workbook = openpyxl.load_workbook(path)
    worksheet = workbook.active
    assert [[cell.value or "" for cell in row] for row in worksheet.rows] == [
        [
            "ID",
            "prénom",
            "nom",
            "nir",
            "date_de_naissance",
        ],
        [
            str(job_seeker_1.pk),
            job_seeker_1.first_name,
            job_seeker_1.last_name.upper(),
            "",
            "31/12/2000",
        ],
        [
            str(job_seeker_2.pk),
            job_seeker_2.first_name,
            job_seeker_2.last_name.upper(),
            job_seeker_2.jobseeker_profile.nir,
            "",
        ],
    ]
