import csv
import datetime
import os
from tempfile import NamedTemporaryFile

from django.contrib.contenttypes.models import ContentType
from django.core import management
from django.utils import timezone
from freezegun import freeze_time

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.models import JobSeekerProfile, User
from itou.utils.models import PkSupportRemark
from itou.www.gps.enums import EndReason
from tests.gps.factories import FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


@freeze_time()
def test_import_advisor_information(settings, caplog, mocker):
    batch_group_creator = ItouStaffFactory()
    settings.GPS_GROUPS_CREATED_BY_EMAIL = batch_group_creator.email

    job_seeker_with_no_correct_data = JobSeekerFactory()
    non_professional = ItouStaffFactory()

    unknown_safir = "22222"
    known_safir = "11111"
    organization = PrescriberOrganizationFactory(code_safir_pole_emploi=known_safir)

    # A job seeker whose advisor is a prescriber that already exists, with no follow up group
    job_seeker_1 = JobSeekerFactory(
        jobseeker_profile__birthdate=None,
        jobseeker_profile__pole_emploi_id="12345678900",
        jobseeker_profile__nir="",
    )
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
    # Already has a ft_gps_id
    job_seeker_3 = JobSeekerFactory(jobseeker_profile__ft_gps_id="kn_9")
    # previous certified referent
    previous_membership_3 = FollowUpGroupMembershipFactory(
        follow_up_group__beneficiary=job_seeker_3, is_referent_certified=True
    )

    # A job seeker whose advisor is a prescriber that does not exist, with a safir that does not exist
    job_seeker_4 = JobSeekerFactory()

    # An old membership that had is_referent_certified=True
    old_certified_referent_membership = FollowUpGroupMembershipFactory(is_referent_certified=True)

    with NamedTemporaryFile("w") as file:
        # write imported file add a column to ignore to ensure the code doesn't crash
        data = [
            [
                "identifiant_gps",
                "nom",
                "prenom",
                "identifiant_local",
                "date_de_naissance",
                "nir",
                "prenom_conseiller",
                "nom_conseiller",
                "code_agence",
                "mail_conseiller",
                "kn_individu_national",
            ],
            # missing prenom_conseiller
            [
                job_seeker_with_no_correct_data.pk,
                job_seeker_with_no_correct_data.last_name,
                job_seeker_with_no_correct_data.first_name,
                job_seeker_with_no_correct_data.jobseeker_profile.pole_emploi_id,
                job_seeker_with_no_correct_data.jobseeker_profile.birthdate,
                job_seeker_with_no_correct_data.jobseeker_profile.nir,
                "",
                "Test",
                "Test",
                "Test",
                "kn_1",  # The same job seeker has multple kn_individu_national : ignore all values
            ],
            # missing nom_conseiller
            [
                job_seeker_with_no_correct_data.pk,
                job_seeker_with_no_correct_data.last_name,
                job_seeker_with_no_correct_data.first_name,
                job_seeker_with_no_correct_data.jobseeker_profile.pole_emploi_id,
                job_seeker_with_no_correct_data.jobseeker_profile.birthdate,
                job_seeker_with_no_correct_data.jobseeker_profile.nir,
                "Test",
                "",
                "Test",
                "Test",
                "kn_2",  # The same job seeker has multple kn_individu_national : ignore all values
            ],
            # missing code_agence
            [
                job_seeker_with_no_correct_data.pk,
                job_seeker_with_no_correct_data.last_name,
                job_seeker_with_no_correct_data.first_name,
                job_seeker_with_no_correct_data.jobseeker_profile.pole_emploi_id,
                job_seeker_with_no_correct_data.jobseeker_profile.birthdate,
                job_seeker_with_no_correct_data.jobseeker_profile.nir,
                "Test",
                "Test",
                "",
                "Test",
                "kn_3",  # The same job seeker has multple kn_individu_national : ignore all values
            ],
            # missing mail_conseiller
            [
                job_seeker_with_no_correct_data.pk,
                job_seeker_with_no_correct_data.last_name,
                job_seeker_with_no_correct_data.first_name,
                job_seeker_with_no_correct_data.jobseeker_profile.pole_emploi_id,
                job_seeker_with_no_correct_data.jobseeker_profile.birthdate,
                job_seeker_with_no_correct_data.jobseeker_profile.nir,
                "Test",
                "Test",
                "Test",
                "",
                "kn_4",  # The same job seeker has multple kn_individu_national : ignore all values
            ],
            # mail_conseiller is used by an non professional
            [
                job_seeker_with_no_correct_data.pk,
                job_seeker_with_no_correct_data.last_name,
                job_seeker_with_no_correct_data.first_name,
                job_seeker_with_no_correct_data.jobseeker_profile.pole_emploi_id,
                job_seeker_with_no_correct_data.jobseeker_profile.birthdate,
                job_seeker_with_no_correct_data.jobseeker_profile.nir,
                "Test",
                "Test",
                "Test",
                non_professional.email,
                "kn_5",  # The same job seeker has multple kn_individu_national : ignore all values
            ],
            # Not a job seeker
            [
                prescriber_1.pk,
                prescriber_1.last_name,
                prescriber_1.first_name,
                "",
                "",
                "",
                "Test",
                "Test",
                "Test",
                "Test",
                "kn_6",  # Also ignored as it's not a job seeker
            ],
            # correct data
            [
                job_seeker_1.pk,
                job_seeker_1.last_name,
                job_seeker_1.first_name,
                job_seeker_1.jobseeker_profile.pole_emploi_id,
                job_seeker_1.jobseeker_profile.birthdate,
                job_seeker_1.jobseeker_profile.nir,
                "prescriber_1_first_name",  # This value isn't used
                "prescriber_1_last_name",  # This value isn't used
                known_safir,  # This will be ignored as the prescriber already exists
                prescriber_1.email,
                "kn_7",
            ],
            [
                job_seeker_2.pk,
                job_seeker_2.last_name,
                job_seeker_2.first_name,
                job_seeker_2.jobseeker_profile.pole_emploi_id,
                job_seeker_2.jobseeker_profile.birthdate,
                job_seeker_2.jobseeker_profile.nir,
                "prescriber_2_first_name",  # This value isn't used
                "prescriber_2_last_name",  # This value isn't used
                unknown_safir,  # This will be ignored as the prescriber already exists
                prescriber_2.email,
                "kn_8",
            ],
            [
                job_seeker_3.pk,
                job_seeker_3.last_name,
                job_seeker_3.first_name,
                job_seeker_3.jobseeker_profile.pole_emploi_id,
                job_seeker_3.jobseeker_profile.birthdate,
                job_seeker_3.jobseeker_profile.nir,
                "Alphonse",
                "Armani",
                known_safir,
                "alphonse.armani@mailinator.com",
                "kn_9",  # It was already there, don't update it
            ],
            [
                job_seeker_4.pk,
                "Jean Claude",
                job_seeker_4.first_name,
                job_seeker_4.jobseeker_profile.pole_emploi_id,
                job_seeker_4.jobseeker_profile.birthdate,
                job_seeker_4.jobseeker_profile.nir,
                "Beatrice",
                "Balladur",
                unknown_safir,
                "beatrice.balladur@mailinator.com",
                "kn_10",  # This name changed, don't update the kn_individu_national
            ],
        ]
        writer = csv.writer(file, delimiter=";")
        writer.writerows(data)
        file.seek(0)
        management.call_command("import_advisor_information", file.name, wet_run=True)

    # Check ft_gps_id: only the job seekers with only one value will be updated:
    assert list(
        JobSeekerProfile.objects.filter(ft_gps_id__isnull=False).order_by("pk").values_list("pk", "ft_gps_id")
    ) == [
        (job_seeker_1.pk, "kn_7"),
        (job_seeker_2.pk, "kn_8"),
        (job_seeker_3.pk, "kn_9"),
    ]

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
    assert prescriber_3.is_professional
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
    assert prescriber_4.is_professional
    assert not prescriber_4.prescribermembership_set.exists()
    user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=prescriber_4.pk).get()
    assert user_remark.remark == "Créé par l'import des référents FT pour GPS"

    assert caplog.messages[:-1] == [
        "Some job seekers were found multiple times, their ft_gps_id won't be saved: 1 jobseekers",
        "Found 6 rows from GPS export.",  # 10 minus the 4 with missing data
        f"Some job seekers ids where not found: [{prescriber_1.pk}].",
        f"Some advisor email are attached to non professional accounts: ['{non_professional.email}'].",
        "Updated 2 ft_gps_id values the database",
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

    job_seeker_1 = JobSeekerFactory(
        post_code="30000",
        jobseeker_profile__birthdate=datetime.date(2000, 12, 31),
        jobseeker_profile__nir="",
        jobseeker_profile__ft_gps_id="0dbcc6ef-6831-4312-ab33-79538d891bdd",
    )
    job_seeker_2 = JobSeekerFactory(
        post_code="40000",
        jobseeker_profile__birthdate=None,
        jobseeker_profile__nir="188073512757119",
        jobseeker_profile__pole_emploi_id="12345678900",
    )

    management.call_command("export_beneficiaries_for_advisor")
    path = os.path.join(settings.EXPORT_DIR, "gps_export_beneficiaires_2025-04-03_11:44.csv")
    with open(path) as file:
        data = [line for line in csv.reader(file, delimiter=";")]
    assert data == [
        [
            "ID - emplois",
            "ID - FT",
            "Prénom",
            "Nom",
            "NIR",
            "Identifiant FT",
            "Date de naissance",
        ],
        [
            str(job_seeker_1.pk),
            "0dbcc6ef-6831-4312-ab33-79538d891bdd",
            job_seeker_1.first_name,
            job_seeker_1.last_name.upper(),
            "",
            "",
            "31/12/2000",
        ],
        [
            str(job_seeker_2.pk),
            "",
            job_seeker_2.first_name,
            job_seeker_2.last_name.upper(),
            "188073512757119",
            "12345678900",
            "",
        ],
    ]

    management.call_command("export_beneficiaries_for_advisor", "30", "40")
    path = os.path.join(settings.EXPORT_DIR, "gps_export_beneficiaires_2025-04-03_11:44.csv")
    with open(path) as file:
        data = [line for line in csv.reader(file, delimiter=";")]
    assert data == [
        [
            "ID - emplois",
            "ID - FT",
            "Prénom",
            "Nom",
            "NIR",
            "Identifiant FT",
            "Date de naissance",
        ],
        [
            str(job_seeker_1.pk),
            "0dbcc6ef-6831-4312-ab33-79538d891bdd",
            job_seeker_1.first_name,
            job_seeker_1.last_name.upper(),
            "",
            "",
            "31/12/2000",
        ],
        [
            str(job_seeker_2.pk),
            "",
            job_seeker_2.first_name,
            job_seeker_2.last_name.upper(),
            "188073512757119",
            "12345678900",
            "",
        ],
    ]

    management.call_command("export_beneficiaries_for_advisor", "30")
    path = os.path.join(settings.EXPORT_DIR, "gps_export_beneficiaires_2025-04-03_11:44.csv")
    with open(path) as file:
        data = [line for line in csv.reader(file, delimiter=";")]
    assert data == [
        [
            "ID - emplois",
            "ID - FT",
            "Prénom",
            "Nom",
            "NIR",
            "Identifiant FT",
            "Date de naissance",
        ],
        [
            str(job_seeker_1.pk),
            "0dbcc6ef-6831-4312-ab33-79538d891bdd",
            job_seeker_1.first_name,
            job_seeker_1.last_name.upper(),
            "",
            "",
            "31/12/2000",
        ],
    ]
