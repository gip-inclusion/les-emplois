import datetime
import random

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.archive.management.commands.notify_archive_jobseekers import GRACE_PERIOD
from itou.archive.models import ArchivedJobSeeker
from itou.users.models import User
from tests.approvals.factories import ApprovalFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.gps.factories import FollowUpGroupFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


class TestNotifyArchiveJobSeekersManagementCommand:
    @pytest.mark.parametrize("wet_run", [True, False])
    @pytest.mark.parametrize(
        "kwargs, model",
        [
            pytest.param(
                {"joined_days_ago": 365},
                "user",
                id="jobseeker_to_notify",
            ),
            pytest.param(
                {"joined_days_ago": 365, "notified_days_ago": 1, "last_login": timezone.now()},
                "user",
                id="notified_jobseeker_to_reset",
            ),
            pytest.param(
                {"joined_days_ago": 365, "notified_days_ago": 30},
                "archived_jobseeker",
                id="jobseeker_to_archive",
            ),
        ],
    )
    def test_dry_run(self, kwargs, model, wet_run):
        jobseeker = JobSeekerFactory(**kwargs)
        call_command("notify_archive_jobseekers", wet_run=wet_run)

        if not wet_run:
            assert jobseeker == User.objects.get()
            assert not ArchivedJobSeeker.objects.exists()
        elif model == "user":
            assert User.objects.filter(upcoming_deletion_notified_at__isnull=jobseeker.last_login is not None).exists()
            assert not ArchivedJobSeeker.objects.exists()
        elif model == "archived_jobseeker":
            assert ArchivedJobSeeker.objects.count() == 1
            assert not User.objects.exists()

    @pytest.mark.parametrize(
        "kwargs, model, pending_user_expected_value",
        [
            pytest.param(
                {"joined_days_ago": 365},
                "user",
                None,
                id="jobseeker_to_notify",
            ),
            pytest.param(
                {"joined_days_ago": 365, "notified_days_ago": 30},
                "archived_jobseeker",
                None,
                id="jobseeker_to_archive",
            ),
        ],
    )
    def test_batch_size(self, kwargs, model, pending_user_expected_value):
        JobSeekerFactory.create_batch(3, **kwargs)
        call_command("notify_archive_jobseekers", batch_size=2, wet_run=True)

        if model == "user":
            assert User.objects.filter(upcoming_deletion_notified_at=pending_user_expected_value).count() == 1
            assert User.objects.exclude(upcoming_deletion_notified_at=pending_user_expected_value).count() == 2
        else:
            assert ArchivedJobSeeker.objects.count() == 2
            assert User.objects.count() == 1

    @pytest.mark.parametrize(
        "factory, related_object_factory, updated_notification_date",
        [
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, for_snapshot=True),
                None,
                True,
                id="jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, is_active=False),
                None,
                True,
                id="deactivated_jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now()),
                None,
                False,
                id="jobseeker_with_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                False,
                id="jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365),
                lambda jobseeker: ApprovalFactory(user=jobseeker),
                False,
                id="jobseeker_with_recent_approval",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365),
                lambda jobseeker: IAEEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                False,
                id="jobseeker_with_recent_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365),
                lambda jobseeker: GEIQEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                False,
                id="jobseeker_with_recent_geiq_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365),
                lambda jobseeker: FollowUpGroupFactory(beneficiary=jobseeker),
                False,
                id="jobseeker_with_recent_follow_up_group",
            ),
            pytest.param(
                lambda: PrescriberFactory(joined_days_ago=365),
                None,
                False,
                id="prescriber_without_recent_activity",
            ),
            pytest.param(
                lambda: EmployerFactory(joined_days_ago=365),
                None,
                False,
                id="employer_without_recent_activity",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(joined_days_ago=365),
                None,
                False,
                id="labor_inspector_without_recent_activity",
            ),
            pytest.param(
                lambda: ItouStaffFactory(joined_days_ago=365),
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
            call_command("notify_archive_jobseekers", wet_run=True)

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
                assert body == snapshot(name="inactive_jobseeker_email")
            else:
                assert not mailoutbox

        else:
            assert "Notified inactive job seekers without recent activity: 0" in caplog.messages
            assert not mailoutbox

    @pytest.mark.parametrize(
        "factory, related_object_factory, notification_reset",
        [
            pytest.param(
                lambda: JobSeekerFactory(
                    joined_days_ago=365,
                    notified_days_ago=29,
                ),
                None,
                False,
                id="notified_jobseeker",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1, last_login=timezone.now()),
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
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1, is_active=False),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                True,
                id="inactive_jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1),
                lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
                True,
                id="notified_jobseeker_with_recent_job_application",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1),
                lambda jobseeker: ApprovalFactory(user=jobseeker),
                True,
                id="notified_jobseeker_with_recent_approval",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1),
                lambda jobseeker: IAEEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                True,
                id="notified_jobseeker_with_recent_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1),
                lambda jobseeker: GEIQEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
                True,
                id="notified_jobseeker_with_recent_geiq_eligibility_diagnosis",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=365, notified_days_ago=1),
                lambda jobseeker: FollowUpGroupFactory(beneficiary=jobseeker),
                True,
                id="notified_jobseeker_with_recent_follow_up_group",
            ),
            pytest.param(
                lambda: ItouStaffFactory(joined_days_ago=365, notified_days_ago=1, last_login=timezone.now()),
                None,
                False,
                id="itoustaff_with_recent_login",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(joined_days_ago=365, notified_days_ago=1, last_login=timezone.now()),
                None,
                False,
                id="labor_inspector_with_recent_login",
            ),
            pytest.param(
                lambda: EmployerFactory(joined_days_ago=365, notified_days_ago=1, last_login=timezone.now()),
                None,
                False,
                id="employer_with_recent_login",
            ),
            pytest.param(
                lambda: PrescriberFactory(joined_days_ago=365, notified_days_ago=1, last_login=timezone.now()),
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

        call_command("notify_archive_jobseekers", wet_run=True)

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
        call_command("notify_archive_jobseekers", wet_run=True)

        expected_user = User.objects.get()
        assert user == expected_user
        assert not ArchivedJobSeeker.objects.exists()

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param(
                {
                    "first_name": "Johanna",
                    "last_name": "Andrews",
                    "joined_days_ago": 50,
                    "first_login": timezone.now() - datetime.timedelta(days=50),
                    "last_login": timezone.now() - datetime.timedelta(days=50),
                    "created_by": random.choice([PrescriberFactory, EmployerFactory, None]),
                    "jobseeker_profile__pole_emploi_id": "12345678",
                    "jobseeker_profile__nir": "855456789012345",
                    "jobseeker_profile__lack_of_nir_reason": "",
                    "jobseeker_profile__birthdate": datetime.date(1990, 1, 1),
                },
                id="jobseeker_with_all_datas",
            ),
            pytest.param(
                {
                    "first_name": "Martin",
                    "last_name": "Jacobson",
                    "joined_days_ago": 50,
                    "first_login": None,
                    "last_login": None,
                    "created_by": None,
                    "jobseeker_profile__pole_emploi_id": "",
                    "jobseeker_profile__nir": "",
                    "jobseeker_profile__lack_of_nir_reason": "reason",
                    "jobseeker_profile__birthdate": None,
                },
                id="jobseeker_with_very_few_datas",
            ),
            pytest.param(
                {
                    "first_name": "Stephan",
                    "last_name": "Xiao",
                    "joined_days_ago": 50,
                    "is_active": False,
                },
                id="jobseeker_not_is_active",
            ),
        ],
    )
    def test_archive_inactive_jobseekers_after_grace_period(
        self, kwargs, django_capture_on_commit_callbacks, caplog, mailoutbox, snapshot
    ):
        if "created_by" in kwargs and kwargs["created_by"]:
            kwargs["created_by"] = kwargs["created_by"]()

        jobseeker = JobSeekerFactory(notified_days_ago=31, **kwargs)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_archive_jobseekers", wet_run=True)

        assert not User.objects.filter(id=jobseeker.id).exists()

        archived_jobseeker = ArchivedJobSeeker.objects.get()
        assert archived_jobseeker.date_joined == timezone.localdate(jobseeker.date_joined).replace(day=1)
        assert archived_jobseeker.first_login == (
            timezone.localdate(jobseeker.first_login).replace(day=1) if jobseeker.first_login else None
        )
        assert archived_jobseeker.last_login == (
            timezone.localdate(jobseeker.last_login).replace(day=1) if jobseeker.last_login else None
        )
        assert archived_jobseeker.user_signup_kind == (jobseeker.created_by.kind if jobseeker.created_by else None)
        assert archived_jobseeker.department == jobseeker.department
        assert archived_jobseeker.title == jobseeker.title
        assert archived_jobseeker.identity_provider == jobseeker.identity_provider

        assert archived_jobseeker.had_pole_emploi_id == bool(jobseeker.jobseeker_profile.pole_emploi_id)
        assert archived_jobseeker.had_nir == bool(jobseeker.jobseeker_profile.nir)
        assert archived_jobseeker.lack_of_nir_reason == jobseeker.jobseeker_profile.lack_of_nir_reason
        assert archived_jobseeker.nir_sex == (
            int(jobseeker.jobseeker_profile.nir[0]) if jobseeker.jobseeker_profile.nir else None
        )
        assert archived_jobseeker.nir_year == (
            int(jobseeker.jobseeker_profile.nir[1:3]) if jobseeker.jobseeker_profile.nir else None
        )
        assert archived_jobseeker.birth_year == (
            int(jobseeker.jobseeker_profile.birthdate.year) if jobseeker.jobseeker_profile.birthdate else None
        )

        assert "Archived jobseekers after grace period, count: 1" in caplog.messages
        if jobseeker.is_active:
            [mail] = mailoutbox
            assert jobseeker.email == mail.to[0]
            assert mail.subject == snapshot(name="archived_jobseeker_email_subject")

            body = mail.body.replace(
                timezone.localdate(jobseeker.upcoming_deletion_notified_at).strftime("%d/%m/%Y"), "XX/XX/XXXX"
            )
            assert body == snapshot(name="archived_jobseeker_email")
        else:
            assert not mailoutbox
