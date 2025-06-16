import datetime

import httpx
import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from itou.archive.models import AnonymizedApplication, AnonymizedJobSeeker
from itou.companies.enums import CompanyKind, ContractNature, ContractType
from itou.files.models import File
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.jobs.models import Appellation, Rome
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.constants import DAYS_OF_INACTIVITY, GRACE_PERIOD, INACTIVITY_PERIOD
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import JobDescriptionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.files.factories import FileFactory
from tests.gps.factories import FollowUpGroupFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.fixture(name="brevo_api_key", autouse=True)
def brevo_api_key_fixture(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"


class TestNotifyInactiveUsersManagementCommand:
    def test_dry_run(self, django_capture_on_commit_callbacks, mailoutbox):
        user = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_users")

        user.refresh_from_db()
        assert not mailoutbox
        assert user.upcoming_deletion_notified_at is None

    def test_notify_batch_size(self):
        JobSeekerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY)
        call_command("notify_inactive_users", batch_size=2, wet_run=True)

        assert User.objects.filter(upcoming_deletion_notified_at__isnull=True).count() == 1
        assert User.objects.exclude(upcoming_deletion_notified_at__isnull=True).count() == 2

    @pytest.mark.parametrize(
        "factory, related_object_factory, updated_notification_date",
        [
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                None,
                True,
                id="jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, is_active=False),
                None,
                True,
                id="deactivated_jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY - 1, for_snapshot=True),
                None,
                False,
                id="jobseeker_soon_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, last_login=timezone.now()),
                None,
                False,
                id="jobseeker_with_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                lambda jobseeker: JobApplicationFactory(
                    job_seeker=jobseeker, eligibility_diagnosis=None, updated_at=timezone.now() - INACTIVITY_PERIOD
                ),
                True,
                id="jobseeker_with_job_application_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                False,
                id="jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                lambda jobseeker: ApprovalFactory(user=jobseeker),
                False,
                id="jobseeker_with_recent_approval",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                lambda jobseeker: IAEEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                False,
                id="jobseeker_with_recent_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                lambda jobseeker: GEIQEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                False,
                id="jobseeker_with_recent_geiq_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                lambda jobseeker: FollowUpGroupFactory(
                    beneficiary=jobseeker, updated_at=timezone.now() - INACTIVITY_PERIOD
                ),
                True,
                id="jobseeker_in_followup_group_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                lambda jobseeker: FollowUpGroupFactory(beneficiary=jobseeker),
                False,
                id="jobseeker_in_followup_group_with_recent_activity",
            ),
            pytest.param(
                lambda: PrescriberFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                None,
                False,
                id="prescriber_without_recent_activity",
            ),
            pytest.param(
                lambda: EmployerFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                None,
                False,
                id="employer_without_recent_activity",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                None,
                False,
                id="labor_inspector_without_recent_activity",
            ),
            pytest.param(
                lambda: ItouStaffFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                None,
                False,
                id="itou_staff_without_recent_activity",
            ),
        ],
    )
    def test_notify_inactive_jobseekers(
        self,
        factory,
        related_object_factory,
        updated_notification_date,
        django_capture_on_commit_callbacks,
        caplog,
        mailoutbox,
        snapshot,
    ):
        user = factory()
        if related_object_factory:
            related_object_factory(user)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_users", wet_run=True)

        user.refresh_from_db()
        assert (user.upcoming_deletion_notified_at is not None) == updated_notification_date

        if updated_notification_date:
            assert "Notified inactive job seekers without recent activity: 1" in caplog.messages

            if user.is_active:
                [mail] = mailoutbox
                assert [user.email] == mail.to
                assert mail.subject == snapshot(name="inactive_jobseeker_email_subject")
                fmt_date_joined = timezone.localdate(user.date_joined).strftime("%d/%m/%Y")
                fmt_end_of_grace = (timezone.localdate(user.upcoming_deletion_notified_at) + GRACE_PERIOD).strftime(
                    "%d/%m/%Y"
                )
                body = mail.body.replace(fmt_date_joined, "XX/XX/XXXX").replace(fmt_end_of_grace, "YY/YY/YYYY")
                assert body == snapshot(name="inactive_jobseeker_email_body")
            else:
                assert not mailoutbox

        else:
            assert "Notified inactive job seekers without recent activity: 0" in caplog.messages
            assert not mailoutbox


class TestArchiveUsersManagementCommand:
    @pytest.mark.parametrize("suspended", [True, False])
    @pytest.mark.parametrize("wet_run", [True, False])
    def test_suspend_command_setting(self, settings, suspended, wet_run, caplog, snapshot):
        settings.SUSPEND_ANONYMIZE_USERS = suspended
        call_command("anonymize_users", wet_run=wet_run)
        assert caplog.messages[0] == snapshot(name="suspend_anonymize_users_command_log")

    def test_dry_run(self):
        JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)
        call_command("anonymize_users")

        User.objects.get()
        assert not AnonymizedJobSeeker.objects.exists()
        assert not AnonymizedApplication.objects.exists()

    def test_archive_batch_size(self):
        JobSeekerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)
        call_command("anonymize_users", batch_size=2, wet_run=True)

        assert AnonymizedJobSeeker.objects.count() == 2
        assert User.objects.count() == 1

    @pytest.mark.parametrize(
        "factory, related_object_factory, notification_reset",
        [
            pytest.param(
                lambda: JobSeekerFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY,
                    notified_days_ago=29,
                ),
                None,
                False,
                id="notified_jobseeker",
            ),
            pytest.param(
                lambda: JobSeekerFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
                ),
                None,
                True,
                id="notified_jobseeker_with_recent_login",
            ),
            pytest.param(
                lambda: JobSeekerFactory(
                    date_joined=timezone.now(),
                    notified_days_ago=1,
                ),
                None,
                True,
                id="notified_jobseeker_with_recent_date_joined",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, is_active=False),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                True,
                id="inactive_jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                True,
                id="notified_jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1),
                lambda jobseeker: ApprovalFactory(user=jobseeker),
                True,
                id="notified_jobseeker_with_recent_approval",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1),
                lambda jobseeker: IAEEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                True,
                id="notified_jobseeker_with_recent_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1),
                lambda jobseeker: GEIQEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                True,
                id="notified_jobseeker_with_recent_geiq_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1),
                lambda jobseeker: FollowUpGroupFactory(beneficiary=jobseeker),
                True,
                id="notified_jobseeker_with_recent_follow_up_group",
            ),
            pytest.param(
                lambda: ItouStaffFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
                ),
                None,
                False,
                id="itoustaff_with_recent_login",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
                ),
                None,
                False,
                id="labor_inspector_with_recent_login",
            ),
            pytest.param(
                lambda: EmployerFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
                ),
                None,
                False,
                id="employer_with_recent_login",
            ),
            pytest.param(
                lambda: PrescriberFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
                ),
                None,
                False,
                id="prescriber_with_recent_login",
            ),
        ],
    )
    def test_reset_notified_jobseekers_with_recent_activity(self, factory, related_object_factory, notification_reset):
        user = factory()
        if related_object_factory:
            related_object_factory(user)

        call_command("anonymize_users", wet_run=True)

        user.refresh_from_db()
        assert (user.upcoming_deletion_notified_at is None) == notification_reset

    @pytest.mark.parametrize(
        "user_factory",
        [
            pytest.param(
                lambda: JobSeekerFactory(
                    notified_days_ago=29,
                ),
                id="jobseeker_notified_still_in_grace_period",
            ),
            pytest.param(
                lambda: JobSeekerFactory(
                    upcoming_deletion_notified_at=None,
                ),
                id="jobseeker_never_notified",
            ),
            pytest.param(
                lambda: EmployerFactory(is_active=False, notified_days_ago=30),
                id="employer",
            ),
            pytest.param(
                lambda: PrescriberFactory(notified_days_ago=30),
                id="prescriber",
            ),
            pytest.param(
                lambda: ItouStaffFactory(notified_days_ago=30),
                id="itou_staff",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(notified_days_ago=30),
                id="laborinspector",
            ),
        ],
    )
    def test_exclude_users_when_archiving(self, user_factory):
        user = user_factory()
        call_command("anonymize_users", wet_run=True)

        expected_user = User.objects.get()
        assert user == expected_user
        assert not AnonymizedJobSeeker.objects.exists()

    @pytest.mark.parametrize(
        "kwargs,jobapplication_kwargs_list",
        [
            pytest.param(
                {
                    "title": "MME",
                    "first_name": "Johanna",
                    "last_name": "Andrews",
                    "date_joined": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                    "first_login": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                    "last_login": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                    "created_by": PrescriberFactory,
                    "jobseeker_profile__pole_emploi_id": "12345678",
                    "jobseeker_profile__nir": "855456789012345",
                    "jobseeker_profile__lack_of_nir_reason": "",
                    "jobseeker_profile__birthdate": datetime.date(1985, 6, 8),
                },
                [
                    {
                        "state": JobApplicationState.ACCEPTED,
                        "sent_by_authorized_prescriber_organisation": True,
                    },
                    {
                        "state": JobApplicationState.POSTPONED,
                        "sent_by_authorized_prescriber_organisation": True,
                    },
                ],
                id="jobseeker_with_all_datas_created_by_prescriber",
            ),
            pytest.param(
                {
                    "title": "MME",
                    "first_name": "Johan",
                    "last_name": "Anderson",
                    "date_joined": timezone.make_aware(datetime.datetime(2021, 12, 12, 0, 0)),
                    "first_login": timezone.make_aware(datetime.datetime(2021, 12, 13, 0, 0)),
                    "last_login": timezone.make_aware(datetime.datetime(2021, 12, 14, 0, 0)),
                    "created_by": EmployerFactory,
                    "jobseeker_profile__pole_emploi_id": "45678123",
                    "jobseeker_profile__nir": "655456789012345",
                    "jobseeker_profile__lack_of_nir_reason": "",
                    "jobseeker_profile__birthdate": datetime.date(1990, 12, 15),
                },
                [
                    {
                        "state": JobApplicationState.NEW,
                        "to_company__kind": CompanyKind.EA,
                        "sent_by_another_employer": True,
                    },
                    {
                        "state": JobApplicationState.ACCEPTED,
                        "to_company__kind": CompanyKind.EA,
                        "sent_by_another_employer": True,
                    },
                ],
                id="jobseeker_with_all_datas_created_by_employer",
            ),
            pytest.param(
                {
                    "title": "M",
                    "first_name": "Martin",
                    "last_name": "Jacobson",
                    "date_joined": timezone.make_aware(datetime.datetime(2022, 11, 3, 0, 0)),
                    "first_login": None,
                    "last_login": None,
                    "created_by": None,
                    "jobseeker_profile__pole_emploi_id": "",
                    "jobseeker_profile__nir": "",
                    "jobseeker_profile__lack_of_nir_reason": "reason",
                    "jobseeker_profile__birthdate": None,
                },
                [],
                id="jobseeker_with_very_few_datas",
            ),
            pytest.param(
                {
                    "title": "M",
                    "first_name": "Stephan",
                    "last_name": "Xiao",
                    "date_joined": timezone.make_aware(datetime.datetime(2023, 10, 30, 0, 0)),
                    "jobseeker_profile__nir": "74185296365487",
                    "jobseeker_profile__birthdate": datetime.date(1964, 5, 30),
                    "is_active": False,
                },
                [],
                id="jobseeker_not_is_active",
            ),
        ],
    )
    def test_archive_inactive_jobseekers_after_grace_period(
        self, kwargs, jobapplication_kwargs_list, django_capture_on_commit_callbacks, caplog, mailoutbox, snapshot
    ):
        if kwargs.get("created_by"):
            kwargs["created_by"] = kwargs["created_by"]()

        jobseeker = JobSeekerFactory(notified_days_ago=31, **kwargs)

        for jobapplication_kwargs in jobapplication_kwargs_list:
            if jobapplication_kwargs.get("sender_kind") == UserKind.JOB_SEEKER:
                jobapplication_kwargs["sender"] = jobseeker

            JobApplicationFactory(
                job_seeker=jobseeker,
                approval=None,
                eligibility_diagnosis=None,
                geiq_eligibility_diagnosis=None,
                updated_at=timezone.now() - INACTIVITY_PERIOD,
                **jobapplication_kwargs,
            )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_users", wet_run=True)

        assert not User.objects.filter(id=jobseeker.id).exists()
        assert not JobApplication.objects.filter(job_seeker=jobseeker).exists()

        archived_jobseeker = AnonymizedJobSeeker.objects.all().values(
            "date_joined",
            "first_login",
            "last_login",
            "user_signup_kind",
            "department",
            "title",
            "identity_provider",
            "had_pole_emploi_id",
            "had_nir",
            "lack_of_nir_reason",
            "nir_sex",
            "nir_year",
            "birth_year",
            "count_accepted_applications",
            "count_IAE_applications",
            "count_total_applications",
        )
        assert list(archived_jobseeker) == snapshot(name="archived_jobseeker")

        assert "Anonymized jobseekers after grace period, count: 1" in caplog.messages
        if jobseeker.is_active:
            [mail] = mailoutbox
            assert jobseeker.email == mail.to[0]
            assert mail.subject == snapshot(name="archived_jobseeker_email_subject")

            body = mail.body.replace(
                timezone.localdate(jobseeker.upcoming_deletion_notified_at).strftime("%d/%m/%Y"), "XX/XX/XXXX"
            )
            assert body == snapshot(name="archived_jobseeker_email_body")
        else:
            assert not mailoutbox

    def test_archive_inactive_jobseekers_with_followup_group(self, django_capture_on_commit_callbacks):
        jobseeker = JobSeekerFactory(
            joined_days_ago=365,
            notified_days_ago=31,
        )
        FollowUpGroupFactory(beneficiary=jobseeker, memberships=2, updated_at=timezone.now() - INACTIVITY_PERIOD)

        assert FollowUpGroup.objects.exists()
        assert FollowUpGroupMembership.objects.exists()

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_users", wet_run=True)

        assert not User.objects.filter(id=jobseeker.id).exists()
        assert not FollowUpGroup.objects.exists()
        assert not FollowUpGroupMembership.objects.exists()
        assert AnonymizedJobSeeker.objects.exists()

    @pytest.mark.parametrize("deleted_at", [None, timezone.make_aware(datetime.datetime(2025, 3, 3, 0, 0))])
    def test_archive_inactive_jobseekers_with_file(self, django_capture_on_commit_callbacks, deleted_at):
        resume_file = FileFactory(deleted_at=deleted_at)
        JobApplicationFactory(
            job_seeker__notified_days_ago=31,
            job_seeker__date_joined=timezone.make_aware(datetime.datetime(2023, 10, 30, 0, 0)),
            approval=None,
            eligibility_diagnosis=None,
            geiq_eligibility_diagnosis=None,
            updated_at=timezone.now() - INACTIVITY_PERIOD,
            resume=resume_file,
        )
        undesired_file_keys = [FileFactory().id, JobApplicationFactory().resume.id]

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_users", wet_run=True)

        assert File.objects.filter(id__in=undesired_file_keys, deleted_at__isnull=True).count() == 2

        file = File.objects.get(id=resume_file.id, jobapplication__isnull=True, deleted_at__isnull=False)

        if deleted_at is None:
            assert file.deleted_at.date() == timezone.now().date()
            ("django.urls.reverse",)
        else:
            assert file.deleted_at == deleted_at

    @freeze_time("2025-02-15")
    @pytest.mark.parametrize(
        "kwargs,has_transitions,selected_jobs_count",
        [
            pytest.param(
                {
                    "sent_by_job_seeker": True,
                    "to_company__kind": CompanyKind.GEIQ,
                    "to_company__department": 76,
                    "to_company__naf": "1234Z",
                    "to_company__convention__is_active": True,
                    "was_hired": True,
                    "hired_job__contract_type": ContractType.FIXED_TERM_TREMPLIN,
                    "hired_job__contract_nature": ContractNature.PEC_OFFER,
                    "to_company__romes": ["N1101"],
                    "hiring_start_at": datetime.date(2025, 2, 2),
                    "hiring_without_approval": True,
                },
                True,
                3,
                id="hired_jobseeker_with_3_jobs",
            ),
            pytest.param(
                {
                    "sent_by_job_seeker": True,
                    "to_company__kind": CompanyKind.OPCS,
                    "to_company__department": 76,
                    "to_company__naf": "4567A",
                    "to_company__convention__is_active": False,
                    "to_company__romes": ["N1102"],
                    "state": JobApplicationState.REFUSED,
                    "refusal_reason": "reason",
                    "resume": None,
                },
                False,
                1,
                id="refused_application_with_1_jobs",
            ),
            pytest.param(
                {
                    "sent_by_another_employer": True,
                    "to_company__kind": CompanyKind.EI,
                    "to_company__department": 76,
                    "to_company__naf": "4567A",
                    "to_company__convention": None,
                    "state": JobApplicationState.PROCESSING,
                },
                False,
                0,
                id="application_sent_by_company",
            ),
            pytest.param(
                {
                    "to_company__department": 14,
                    "to_company__kind": CompanyKind.EITI,
                    "to_company__naf": "8888Y",
                    "sent_by_authorized_prescriber_organisation": True,
                    "state": JobApplicationState.PRIOR_TO_HIRE,
                },
                False,
                0,
                id="application_sent_by_authorized_prescriber",
            ),
            pytest.param(
                {
                    "sent_by_another_employer": True,
                    "to_company__kind": CompanyKind.EI,
                    "to_company__department": 76,
                    "to_company__naf": "4567A",
                    "transferred_at": timezone.make_aware(datetime.datetime(2025, 2, 2)),
                    "diagoriente_invite_sent_at": timezone.make_aware(datetime.datetime(2025, 2, 3)),
                    "state": JobApplicationState.POSTPONED,
                },
                False,
                0,
                id="transferred_application_with_diagoriente_invitation",
            ),
            pytest.param(
                {"sent_by_job_seeker": True, "sender": None, "to_company__department": 76, "to_company__naf": "7820Z"},
                True,
                3,
                id="sent_by_jobseeker_without_sender",
            ),
        ],
    )
    def test_archive_not_eligible_jobapplications_of_inactive_jobseekers_after_grace_period(
        self,
        kwargs,
        has_transitions,
        selected_jobs_count,
        django_capture_on_commit_callbacks,
        caplog,
        snapshot,
    ):
        job_seeker = JobSeekerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=30,
            jobseeker_profile__birthdate=datetime.date(1978, 5, 17),
            post_code="76160",
        )
        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            approval=None,
            eligibility_diagnosis=None,
            geiq_eligibility_diagnosis=None,
            updated_at=timezone.now() - INACTIVITY_PERIOD,
            **kwargs,
        )
        if has_transitions:
            for from_state, to_state, months in [
                (JobApplicationState.NEW, JobApplicationState.PROCESSING, 0),
                (JobApplicationState.PROCESSING, JobApplicationState.ACCEPTED, 1),
            ]:
                JobApplicationTransitionLog.objects.create(
                    user=job_seeker,
                    from_state=from_state,
                    to_state=to_state,
                    job_application=job_application,
                    timestamp=job_application.created_at + relativedelta(months=months),
                )
        if selected_jobs_count > 0:
            rome = Rome.objects.create(code="I1304", name="Rome 1304")
            Appellation.objects.create(code="I13042", name="Doer", rome=rome)
            selected_jobs = JobDescriptionFactory.create_batch(selected_jobs_count, company=job_application.to_company)
            job_application.selected_jobs.set(selected_jobs)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_users", wet_run=True)

        archived_application = AnonymizedApplication.objects.all().values(
            "job_seeker_birth_year",
            "job_seeker_department_same_as_company_department",
            "sender_kind",
            "sender_company_kind",
            "sender_prescriber_organization_kind",
            "sender_prescriber_organization_authorization_status",
            "company_kind",
            "company_department",
            "company_naf",
            "company_has_convention",
            "applied_at",
            "processed_at",
            "last_transition_at",
            "had_resume",
            "origin",
            "state",
            "refusal_reason",
            "has_been_transferred",
            "number_of_jobs_applied_for",
            "has_diagoriente_invitation",
            "hiring_rome",
            "hiring_contract_type",
            "hiring_contract_nature",
            "hiring_start_date",
            "hiring_without_approval",
        )
        assert list(archived_application) == snapshot(name="archived_application")
        assert not JobApplication.objects.filter(id=job_application.id).exists()
        assert "Anonymized job applications after grace period, count: 1" in caplog.messages

    def test_async_delete_contact_is_called_when_archiving_user(self, django_capture_on_commit_callbacks, respx_mock):
        jobseekers = JobSeekerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31)
        for jobseeker in jobseekers:
            respx_mock.delete(f"{settings.BREVO_API_URL}/contacts/{jobseeker.email}?identifierType=email_id").mock(
                return_value=httpx.Response(status_code=204)
            )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_users", wet_run=True)

        assert respx_mock.calls.called
        assert respx_mock.calls.call_count == len(jobseekers)
