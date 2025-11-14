import datetime
import random
import re
from unittest.mock import patch
from uuid import uuid1, uuid4

import httpx
import pytest
from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.utils import timezone
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertQuerySetEqual

from itou.approvals.enums import Origin
from itou.approvals.models import Approval, CancelledApproval
from itou.archive.constants import (
    DAYS_OF_GRACE,
    DAYS_OF_INACTIVITY,
    EXPIRATION_PERIOD,
    GRACE_PERIOD,
    INACTIVITY_PERIOD,
)
from itou.archive.models import (
    AnonymizedApplication,
    AnonymizedApproval,
    AnonymizedCancelledApproval,
    AnonymizedGEIQEligibilityDiagnosis,
    AnonymizedJobSeeker,
    AnonymizedProfessional,
    AnonymizedSIAEEligibilityDiagnosis,
)
from itou.companies.enums import CompanyKind
from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models.geiq import (
    GEIQEligibilityDiagnosis,
)
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.files.models import File
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.institutions.models import InstitutionMembership
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import Title, UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.utils.brevo import MalformedResponseException
from itou.utils.models import PkSupportRemark
from tests.approvals.factories import ApprovalFactory, CancelledApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.cities.factories import (
    create_city_geispolsheim,
    create_city_saint_andre,
)
from tests.companies.factories import CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.employee_record.factories import EmployeeRecordFactory
from tests.files.factories import FileFactory
from tests.gps.factories import FollowUpGroupMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.siae_evaluations.factories import EvaluatedJobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerAssignmentFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.fixture(name="brevo_api_key", autouse=True)
def brevo_api_key_fixture(settings):
    settings.BREVO_API_KEY = "BREVO_API_KEY"


@pytest.fixture(autouse=True)
def respx_delete_mock(respx_mock):
    respx_mock = respx_mock.delete(url__regex=re.compile(f"^{re.escape(settings.BREVO_API_URL)}/contacts/.*")).mock(
        return_value=httpx.Response(status_code=204)
    )


@pytest.fixture(autouse=True)
def mock_make_password():
    with patch(
        "itou.archive.management.commands.anonymize_professionals.make_password",
        return_value="pbkdf2_sha256$test$hash",
    ):
        yield


def get_fields_list_for_snapshot(model):
    exclude = {"id", "anonymized_at"}
    fields = [f.name for f in model._meta.get_fields() if f.concrete and f.name not in exclude]
    return sorted(model.objects.values(*fields), key=lambda d: str(d))


class TestNotifyInactiveJobseekersManagementCommand:
    def test_dry_run(self, django_capture_on_commit_callbacks, mailoutbox):
        user = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_jobseekers")

        user.refresh_from_db()
        assert not mailoutbox
        assert user.upcoming_deletion_notified_at is None

    def test_notify_batch_size(self):
        JobSeekerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY)
        call_command("notify_inactive_jobseekers", batch_size=2, wet_run=True)

        assert User.objects.filter(upcoming_deletion_notified_at__isnull=True).count() == 1
        assert User.objects.exclude(upcoming_deletion_notified_at__isnull=True).count() == 2

    def test_users_not_to_notify(self, django_capture_on_commit_callbacks, caplog, mailoutbox):
        # jobseeker_soon_without_recent_activity
        JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY - 1, for_snapshot=True)

        # jobseeker_with_recent_activity
        JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, last_login=timezone.now())

        # jobseeker_with_recent_job_application
        JobApplicationFactory(job_seeker__joined_days_ago=DAYS_OF_INACTIVITY)

        # jobseeker_with_recent_approval
        ApprovalFactory(user__joined_days_ago=DAYS_OF_INACTIVITY)

        # jobseeker_with_recent_eligibility_diagnosis
        IAEEligibilityDiagnosisFactory(job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, from_prescriber=True)

        # jobseeker_with_recent_geiq_eligibility_diagnosis
        GEIQEligibilityDiagnosisFactory(job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, from_prescriber=True)

        # jobseeker_in_followup_group_with_recent_contact
        FollowUpGroupMembershipFactory(follow_up_group__beneficiary__joined_days_ago=DAYS_OF_INACTIVITY)

        # jobseeker_with_evaluated_job_application
        EvaluatedJobApplicationFactory(
            job_application__job_seeker__joined_days_ago=DAYS_OF_INACTIVITY,
            job_application__created_at=timezone.now() - INACTIVITY_PERIOD,
            job_application__eligibility_diagnosis__expires_at=timezone.localdate() - INACTIVITY_PERIOD,
            job_application__approval__start_at=timezone.localdate() - relativedelta(years=3),
            job_application__approval__end_at=timezone.localdate() - INACTIVITY_PERIOD,
        )

        # prescriber_without_recent_activity
        PrescriberFactory(joined_days_ago=DAYS_OF_INACTIVITY)

        # employer_without_recent_activity
        EmployerFactory(joined_days_ago=DAYS_OF_INACTIVITY)

        # labor_inspector_without_recent_activity
        LaborInspectorFactory(joined_days_ago=DAYS_OF_INACTIVITY)

        # itou_staff_without_recent_activity
        ItouStaffFactory(joined_days_ago=DAYS_OF_INACTIVITY)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_jobseekers", wet_run=True)

        assert not User.objects.filter(upcoming_deletion_notified_at__isnull=False).exists()
        assert "Notified inactive job seekers without recent activity: 0" in caplog.messages
        assert not mailoutbox

    @pytest.mark.parametrize(
        "factory, related_object_factory",
        [
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                None,
                id="jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, is_active=False),
                None,
                id="deactivated_jobseeker_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                lambda jobseeker: JobApplicationFactory(
                    job_seeker=jobseeker, created_at=timezone.now() - INACTIVITY_PERIOD
                ),
                id="jobseeker_with_job_application_without_recent_activity",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, for_snapshot=True),
                lambda jobseeker: FollowUpGroupMembershipFactory(
                    follow_up_group__beneficiary=jobseeker, last_contact_at=timezone.now() - INACTIVITY_PERIOD
                ),
                id="jobseeker_in_followup_group_without_recent_contact",
            ),
        ],
    )
    def test_notify_inactive_jobseekers(
        self,
        factory,
        related_object_factory,
        django_capture_on_commit_callbacks,
        caplog,
        mailoutbox,
        snapshot,
    ):
        user = factory()
        if related_object_factory:
            related_object_factory(user)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_jobseekers", wet_run=True)

        user.refresh_from_db()
        assert user.upcoming_deletion_notified_at is not None

        assert "Notified inactive job seekers without recent activity: 1" in caplog.messages

        if user.is_active:
            [mail] = mailoutbox
            assert [user.email] == mail.to
            assert mail.subject == snapshot(name="inactive_jobseeker_email_subject")
            fmt_inactive_since = (timezone.localdate() - INACTIVITY_PERIOD).strftime("%d/%m/%Y")
            fmt_end_of_grace = (timezone.localdate(user.upcoming_deletion_notified_at) + GRACE_PERIOD).strftime(
                "%d/%m/%Y"
            )
            body = mail.body.replace(fmt_inactive_since, "XX/XX/XXXX").replace(fmt_end_of_grace, "YY/YY/YYYY")
            assert body == snapshot(name="inactive_jobseeker_email_body")
        else:
            assert not mailoutbox

    def test_notify_inactive_jobseekers_on_approval_expiration_date(self):
        inactivity_threshold = timezone.localdate() - INACTIVITY_PERIOD
        long_time_ago = timezone.localdate() - relativedelta(years=3)
        approval_kwargs = {
            "user__joined_days_ago": DAYS_OF_INACTIVITY,
            "eligibility_diagnosis__expires_at": long_time_ago,
            "start_at": long_time_ago,
        }

        approval_ended_before_inactivity_threshold = ApprovalFactory(
            end_at=inactivity_threshold,
            **approval_kwargs,
        )

        approval_ended_after_inactivity_threshold = ApprovalFactory(
            end_at=inactivity_threshold + relativedelta(days=1),
            **approval_kwargs,
        )

        job_seeker_with_multiple_approvals = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        for end_at in [inactivity_threshold, timezone.localdate()]:
            ApprovalFactory(
                user=job_seeker_with_multiple_approvals,
                end_at=end_at,
                **approval_kwargs,
            )

        call_command("notify_inactive_jobseekers", wet_run=True)

        assertQuerySetEqual(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=True),
            [approval_ended_after_inactivity_threshold.user, job_seeker_with_multiple_approvals],
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(upcoming_deletion_notified_at__isnull=False),
            [approval_ended_before_inactivity_threshold.user],
        )

    def test_notify_inactive_jobseekers_on_eligibility_diagnosis_expiration_date(self):
        inactivity_threshold = timezone.localdate() - INACTIVITY_PERIOD
        eligibility_kwargs = {
            "job_seeker__joined_days_ago": DAYS_OF_INACTIVITY,
            "from_prescriber": True,
        }

        iae_eligibility_diagnosis_expired_before_inactivity_threshold = IAEEligibilityDiagnosisFactory(
            expires_at=inactivity_threshold,
            **eligibility_kwargs,
        )
        geiq_eligibility_diagnosis_expired_before_inactivity_threshold = GEIQEligibilityDiagnosisFactory(
            expires_at=inactivity_threshold,
            **eligibility_kwargs,
        )

        # Eligibility diagnosis expired after expiration date
        iae_eligibility_diagnosis_expired_after_inactivity_threshold = IAEEligibilityDiagnosisFactory(
            expires_at=inactivity_threshold + relativedelta(days=1),
            **eligibility_kwargs,
        )
        geiq_eligibility_diagnosis_expired_after_inactivity_threshold = GEIQEligibilityDiagnosisFactory(
            expires_at=inactivity_threshold + relativedelta(days=1),
            **eligibility_kwargs,
        )

        # Multiple eligibility diag for the same job seeker, one expired before expiration date, one recently expired
        job_seeker_with_multiple_iae_eligibility_diag = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        for expires_at in [inactivity_threshold, timezone.localdate()]:
            IAEEligibilityDiagnosisFactory(
                job_seeker=job_seeker_with_multiple_iae_eligibility_diag,
                expires_at=expires_at,
                **eligibility_kwargs,
            )
        job_seeker_with_multiple_geiq_eligibility_diag = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        for expires_at in [inactivity_threshold, timezone.localdate()]:
            GEIQEligibilityDiagnosisFactory(
                job_seeker=job_seeker_with_multiple_geiq_eligibility_diag,
                expires_at=expires_at,
                **eligibility_kwargs,
            )

        call_command("notify_inactive_jobseekers", wet_run=True)

        assertQuerySetEqual(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=True),
            [
                iae_eligibility_diagnosis_expired_after_inactivity_threshold.job_seeker,
                geiq_eligibility_diagnosis_expired_after_inactivity_threshold.job_seeker,
                job_seeker_with_multiple_iae_eligibility_diag,
                job_seeker_with_multiple_geiq_eligibility_diag,
            ],
            ordered=False,
        )

        assertQuerySetEqual(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False),
            [
                iae_eligibility_diagnosis_expired_before_inactivity_threshold.job_seeker,
                geiq_eligibility_diagnosis_expired_before_inactivity_threshold.job_seeker,
            ],
            ordered=False,
        )

    def test_notify_inactive_jobseekers_on_job_application_dates(self):
        old_job_application_kwargs = {
            "job_seeker__joined_days_ago": DAYS_OF_INACTIVITY,
            "created_at": timezone.now() - relativedelta(days=DAYS_OF_INACTIVITY),
        }
        recent_job_application_kwargs = {
            **old_job_application_kwargs,
            "created_at": old_job_application_kwargs["created_at"] + relativedelta(days=1),
        }
        log_kwargs = {
            "from_state": JobApplicationState.NEW,
            "to_state": JobApplicationState.PROCESSING,
        }

        # old job application without transition
        old_job_application_without_log = JobApplicationFactory(**old_job_application_kwargs)

        # old job application with old transition
        old_job_application_with_old_log = JobApplicationFactory(**old_job_application_kwargs)
        JobApplicationTransitionLog.objects.create(
            user=old_job_application_with_old_log.job_seeker,
            job_application=old_job_application_with_old_log,
            timestamp=old_job_application_with_old_log.created_at,
            **log_kwargs,
        )

        # old job application with recent transition
        old_job_application_with_recent_log = JobApplicationFactory(**old_job_application_kwargs)
        JobApplicationTransitionLog.objects.create(
            user=old_job_application_with_recent_log.job_seeker,
            job_application=old_job_application_with_recent_log,
            timestamp=old_job_application_with_recent_log.created_at + relativedelta(days=1),
            **log_kwargs,
        )

        # old job application with one old and one recent transitions
        old_job_application_with_multiple_logs = JobApplicationFactory(**old_job_application_kwargs)
        JobApplicationTransitionLog.objects.create(
            user=old_job_application_with_multiple_logs.job_seeker,
            job_application=old_job_application_with_multiple_logs,
            timestamp=old_job_application_with_multiple_logs.created_at,
            **log_kwargs,
        )
        JobApplicationTransitionLog.objects.create(
            user=old_job_application_with_multiple_logs.job_seeker,
            job_application=old_job_application_with_multiple_logs,
            timestamp=old_job_application_with_multiple_logs.created_at + relativedelta(days=1),
            from_state=JobApplicationState.PROCESSING,
            to_state=JobApplicationState.PRIOR_TO_HIRE,
        )

        # recent job application without transition
        recent_job_application_without_log = JobApplicationFactory(**recent_job_application_kwargs)

        # recent job application with recent transition
        recent_job_application_with_recent_log = JobApplicationFactory(**recent_job_application_kwargs)
        JobApplicationTransitionLog.objects.create(
            user=recent_job_application_with_recent_log.job_seeker,
            job_application=recent_job_application_with_recent_log,
            timestamp=recent_job_application_with_recent_log.created_at,
            **log_kwargs,
        )

        call_command("notify_inactive_jobseekers", wet_run=True)

        assertQuerySetEqual(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False),
            [
                old_job_application_without_log.job_seeker,
                old_job_application_with_old_log.job_seeker,
            ],
            ordered=False,
        )

        assertQuerySetEqual(
            User.objects.filter(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=True),
            [
                old_job_application_with_recent_log.job_seeker,
                old_job_application_with_multiple_logs.job_seeker,
                recent_job_application_without_log.job_seeker,
                recent_job_application_with_recent_log.job_seeker,
            ],
            ordered=False,
        )


class TestAnonymizeJobseekersManagementCommand:
    @pytest.mark.parametrize("suspended", [True, False])
    def test_suspend_command_setting(self, settings, suspended, caplog):
        JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)

        settings.SUSPEND_ANONYMIZE_JOBSEEKERS = suspended
        call_command("anonymize_jobseekers", wet_run=True)

        assert ("Anonymizing job seekers is suspended, exiting command" in caplog.messages[0]) is suspended
        assert User.objects.exists() is suspended

    def test_dry_run(self, respx_mock):
        job_application = JobApplicationFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, job_seeker__notified_days_ago=30, with_approval=True
        )
        call_command("anonymize_jobseekers")

        User.objects.get(id=job_application.job_seeker.id)
        JobApplication.objects.get()
        Approval.objects.get()

        assert not AnonymizedJobSeeker.objects.exists()
        assert not AnonymizedApplication.objects.exists()
        assert not AnonymizedApproval.objects.exists()
        assert not respx_mock.calls.called

    def test_archive_batch_size(self, django_capture_on_commit_callbacks, respx_mock):
        JobSeekerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", batch_size=2, wet_run=True)

        assert AnonymizedJobSeeker.objects.count() == 2
        assert User.objects.count() == 1
        assert respx_mock.calls.call_count == 2

    def test_reset_notified_jobseekers_with_recent_activity(self, respx_mock):
        # users which notification date is not reset
        notified_jobseeker = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=29)
        expired_approval_of_notified_jobseeker = ApprovalFactory(
            user__joined_days_ago=DAYS_OF_INACTIVITY,
            user__notified_days_ago=1,
            expired=True,
            eligibility_diagnosis__expires_at=datetime.date(2023, 1, 18),
        )
        itoustaff_with_recent_login = ItouStaffFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
        )
        labor_inspector_with_recent_login = LaborInspectorFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
        )
        employer_with_recent_login = EmployerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
        )
        prescriber_with_recent_login = PrescriberFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
        )

        # users which notification date is reset
        notified_jobseeker_with_recent_login = JobSeekerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now()
        )

        notified_jobseeker_with_recent_date_joined = JobSeekerFactory(
            date_joined=timezone.now(),
            notified_days_ago=1,
        )

        recent_job_application_of_inactive_jobseeker = JobApplicationFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY,
            job_seeker__notified_days_ago=1,
            job_seeker__is_active=False,
        )

        recent_job_application_of_notified_jobseeker = JobApplicationFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, job_seeker__notified_days_ago=1
        )

        recent_approval_of_notified_jobseeker = ApprovalFactory(
            user__joined_days_ago=DAYS_OF_INACTIVITY, user__notified_days_ago=1
        )

        approval_ending_after_grace_period_of_notified_jobseeker = ApprovalFactory(
            user__joined_days_ago=DAYS_OF_INACTIVITY,
            user__notified_days_ago=1,
            expired=True,
            end_at=timezone.localdate() - INACTIVITY_PERIOD + relativedelta(days=1),
        )

        recent_eligibility_diagnosis_of_notified_jobseeker = IAEEligibilityDiagnosisFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, job_seeker__notified_days_ago=1, from_prescriber=True
        )

        recent_geiq_eligibility_diagnosis_of_notified_jobseeker = GEIQEligibilityDiagnosisFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY, job_seeker__notified_days_ago=1, from_prescriber=True
        )

        recent_follow_up_group_contact_of_notified_jobseeker = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__joined_days_ago=DAYS_OF_INACTIVITY,
            follow_up_group__beneficiary__notified_days_ago=1,
        )

        call_command("anonymize_jobseekers", wet_run=True)

        assertQuerySetEqual(
            User.objects.filter(upcoming_deletion_notified_at__isnull=False),
            [
                notified_jobseeker,
                expired_approval_of_notified_jobseeker.user,
                itoustaff_with_recent_login,
                labor_inspector_with_recent_login,
                employer_with_recent_login,
                prescriber_with_recent_login,
            ],
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(upcoming_deletion_notified_at__isnull=True, kind=UserKind.JOB_SEEKER),
            [
                notified_jobseeker_with_recent_login,
                notified_jobseeker_with_recent_date_joined,
                recent_job_application_of_inactive_jobseeker.job_seeker,
                recent_job_application_of_notified_jobseeker.job_seeker,
                recent_approval_of_notified_jobseeker.user,
                approval_ending_after_grace_period_of_notified_jobseeker.user,
                recent_eligibility_diagnosis_of_notified_jobseeker.job_seeker,
                recent_geiq_eligibility_diagnosis_of_notified_jobseeker.job_seeker,
                recent_follow_up_group_contact_of_notified_jobseeker.follow_up_group.beneficiary,
            ],
            ordered=False,
        )
        assert not respx_mock.calls.called

    def test_exclude_users_when_archiving(self, respx_mock):
        jobseeker_notified_still_in_grace_period = JobSeekerFactory(notified_days_ago=29)
        jobseeker_never_notified = JobSeekerFactory(upcoming_deletion_notified_at=None)
        employer = EmployerFactory(is_active=False, notified_days_ago=30)
        prescriber = PrescriberFactory(notified_days_ago=30)
        itou_staff = ItouStaffFactory(notified_days_ago=30)
        labor_inspector = LaborInspectorFactory(notified_days_ago=30)

        call_command("anonymize_jobseekers", wet_run=True)

        assert not AnonymizedJobSeeker.objects.exists()
        assertQuerySetEqual(
            User.objects.all(),
            [
                jobseeker_notified_still_in_grace_period,
                jobseeker_never_notified,
                employer,
                prescriber,
                itou_staff,
                labor_inspector,
            ],
            ordered=False,
        )
        assert not respx_mock.calls.called

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param(
                {"first_name": "Johanna", "last_name": "Andrews"},
                id="is_active_jobseeker",
            ),
            pytest.param(
                {"is_active": False},
                id="not_is_active_jobseeker",
            ),
        ],
    )
    def test_anonymize_notification_of_inactive_jobseekers_after_grace_period(
        self, kwargs, django_capture_on_commit_callbacks, mailoutbox, snapshot, respx_mock, caplog
    ):
        jobseeker = JobSeekerFactory(
            email="jobseeker@example.com", joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31, **kwargs
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

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

        assert respx_mock.calls.call_count == 1

    def test_archive_inactive_jobseekers_with_followup_group(self, django_capture_on_commit_callbacks, respx_mock):
        FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__joined_days_ago=DAYS_OF_INACTIVITY,
            follow_up_group__beneficiary__notified_days_ago=31,
            last_contact_at=timezone.now() - INACTIVITY_PERIOD,
        )

        assert FollowUpGroup.objects.exists()
        assert FollowUpGroupMembership.objects.exists()

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

        assert not User.objects.filter(kind=UserKind.JOB_SEEKER).exists()
        assert not FollowUpGroup.objects.exists()
        assert not FollowUpGroupMembership.objects.exists()
        assert AnonymizedJobSeeker.objects.exists()
        assert respx_mock.calls.call_count == 1

    def test_archive_inactive_jobseekers_with_file(self, django_capture_on_commit_callbacks, respx_mock):
        resume_file = FileFactory()
        JobApplicationFactory(
            job_seeker__notified_days_ago=31,
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY,
            created_at=timezone.now() - INACTIVITY_PERIOD,
            resume=resume_file,
        )
        other_files = [FileFactory(), JobApplicationFactory().resume]

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

        assertQuerySetEqual(File.objects.all(), other_files, ordered=False)
        assert respx_mock.calls.call_count == 1

    def test_archive_inactive_jobseekers_after_grace_period(
        self,
        django_capture_on_commit_callbacks,
        caplog,
        snapshot,
        respx_mock,
    ):
        def _create_job_seeker_with_application(
            job_seeker_kwargs, job_application_kwargs=None, selected_jobs_count=0, transitions=None
        ):
            jobseeker = JobSeekerFactory(notified_days_ago=30, **job_seeker_kwargs)
            if job_application_kwargs:
                job_application = JobApplicationFactory(
                    **job_application_kwargs,
                    job_seeker=jobseeker,
                )
                if transitions:
                    for from_state, to_state, months in transitions:
                        JobApplicationTransitionLog.objects.create(
                            user=jobseeker,
                            from_state=from_state,
                            to_state=to_state,
                            job_application=job_application,
                            timestamp=job_application.created_at + relativedelta(months=months),
                        )
                if selected_jobs_count:
                    jobs = JobDescriptionFactory.create_batch(selected_jobs_count, company=job_application.to_company)
                    job_application.selected_jobs.set(jobs)

        # jobseeker with very few datas, without jobapplication
        # dates to distinguish cases in snapshots : birthdate None - date_joined 2022-11-03
        _create_job_seeker_with_application(
            job_seeker_kwargs={
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
            }
        )

        # jobseeker with all datas, without jobapplication
        # dates to distinguish cases in snapshots : birthdate 1985-06-08 - date_joined 2020-04-18
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "title": "MME",
                "first_name": "Johanna",
                "last_name": "Andrews",
                "date_joined": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                "first_login": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                "last_login": timezone.make_aware(datetime.datetime(2020, 4, 18, 0, 0)),
                "created_by": PrescriberFactory(),
                "jobseeker_profile__pole_emploi_id": "12345678",
                "jobseeker_profile__nir": "855456789012345",
                "jobseeker_profile__lack_of_nir_reason": "",
                "jobseeker_profile__birthdate": datetime.date(1985, 6, 8),
            },
        )

        # hired jobseeker with 3 selected jobs and transition logs
        # dates to distinguish cases in snapshots : birthdate 1970-05-17 - apply at 2022-01-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 1, 15)),
                "jobseeker_profile__birthdate": datetime.date(1970, 5, 17),
                "post_code": "70160",
                "title": Title.MME,
                "jobseeker_profile__nir": "27005987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 1, 15)),
                "sent_by_job_seeker": True,
                "to_company__kind": CompanyKind.GEIQ,
                "to_company__department": 70,
                "to_company__naf": "4570A",
                "was_hired": True,
                "hired_job__contract_type": "PERMANENT_I",
                "to_company__romes": ["N1101"],
                "hiring_start_at": datetime.date(2025, 2, 2),
                "processed_at": timezone.make_aware(datetime.datetime(2022, 2, 15)),
            },
            selected_jobs_count=3,
            transitions=[
                (JobApplicationState.NEW, JobApplicationState.PROCESSING, 0),
                (JobApplicationState.PROCESSING, JobApplicationState.ACCEPTED, 1),
            ],
        )

        # refused job seeker application with 1 job and no transition log
        # dates to distinguish cases in snapshots : birthdate 1971-05-17 - apply at 2022-02-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 2, 15)),
                "jobseeker_profile__birthdate": datetime.date(1971, 5, 17),
                "post_code": "71160",
                "title": Title.M,
                "jobseeker_profile__nir": "17105987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 2, 15)),
                "sent_by_job_seeker": True,
                "to_company__kind": CompanyKind.OPCS,
                "to_company__department": 71,
                "to_company__naf": "4571A",
                "to_company__romes": ["N1102"],
                "state": JobApplicationState.REFUSED,
                "refusal_reason": "reason",
                "resume": None,
                "hiring_start_at": None,
                "processed_at": timezone.make_aware(datetime.datetime(2022, 3, 1)),
            },
            selected_jobs_count=1,
        )

        # application sent by company, no selected job nor transition log
        # dates to distinguish cases in snapshots : birthdate 1972-05-17 - apply at 2022-03-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 3, 15)),
                "jobseeker_profile__birthdate": datetime.date(1972, 5, 17),
                "post_code": "72160",
                "title": Title.MME,
                "jobseeker_profile__nir": "27205987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 3, 15)),
                "sent_by_another_employer": True,
                "sender_company__kind": CompanyKind.EI,
                "to_company__kind": CompanyKind.EI,
                "to_company__department": 72,
                "to_company__naf": "4572A",
                "to_company__convention__is_active": False,
                "state": JobApplicationState.PROCESSING,
                "hiring_start_at": None,
                "processed_at": None,
            },
        )

        # application sent by authorized prescriber, no selected jobs nor transition log
        # dates to distinguish cases in snapshots : birthdate 1973-05-17 - apply at 2022-04-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 4, 15)),
                "jobseeker_profile__birthdate": datetime.date(1973, 5, 17),
                "post_code": "73160",
                "title": Title.M,
                "jobseeker_profile__nir": "17305987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 4, 15)),
                "to_company__department": 73,
                "to_company__kind": CompanyKind.EITI,
                "to_company__naf": "4573A",
                "sent_by_authorized_prescriber_organisation": True,
                "state": JobApplicationState.PRIOR_TO_HIRE,
                "hiring_start_at": None,
            },
        )

        # transferred job application with diagoriente invitation, no selected jobs nor transition log
        # dates to distinguish cases in snapshots : birthdate 1974-05-17 - apply at 2022-05-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 5, 15)),
                "jobseeker_profile__birthdate": datetime.date(1974, 5, 17),
                "post_code": "74160",
                "title": Title.MME,
                "jobseeker_profile__nir": "27405987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 5, 15)),
                "sent_by_another_employer": True,
                "sender_company__kind": CompanyKind.EI,
                "to_company__kind": CompanyKind.EI,
                "to_company__department": 74,
                "to_company__naf": "4574A",
                "transferred_at": timezone.make_aware(datetime.datetime(2022, 6, 2)),
                "diagoriente_invite_sent_at": timezone.make_aware(datetime.datetime(2022, 7, 3)),
                "state": JobApplicationState.POSTPONED,
                "hiring_start_at": None,
            },
        )

        # job application sent by jobseeker him/herself without sender, with 2 selected jobs and transition log
        # dates to distinguish cases in snapshots : birthdate 1978-05-17 - apply at 2022-06-15
        _create_job_seeker_with_application(
            job_seeker_kwargs={
                "date_joined": timezone.make_aware(datetime.datetime(2022, 6, 15)),
                "jobseeker_profile__birthdate": datetime.date(1978, 5, 17),
                "post_code": "78160",
                "title": Title.M,
                "jobseeker_profile__nir": "17805987654321",
            },
            job_application_kwargs={
                "created_at": timezone.make_aware(datetime.datetime(2022, 6, 15)),
                "to_company__kind": CompanyKind.EI,
                "to_company__department": 78,
                "to_company__naf": "4578A",
                "sent_by_job_seeker": True,
                "sender": None,
                "hiring_start_at": None,
            },
            selected_jobs_count=2,
            transitions=[
                (JobApplicationState.NEW, JobApplicationState.PROCESSING, 0),
            ],
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

        assert not JobApplication.objects.exists()
        assert not User.objects.filter(kind=UserKind.JOB_SEEKER).exists()
        assert get_fields_list_for_snapshot(AnonymizedApplication) == snapshot(name="archived_application")
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")
        assert "Anonymized jobseekers after grace period, count: 8" in caplog.messages
        assert "Anonymized job applications after grace period, count: 6" in caplog.messages

        assert respx_mock.calls.call_count == 8

    def test_archived_jobseekers_applications_counts(self, snapshot):
        job_seeker = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31)
        job_application_kwargs = {
            "job_seeker": job_seeker,
            "approval": None,
            "sent_by_job_seeker": True,
            "created_at": timezone.make_aware(datetime.datetime(2022, 1, 15)),
        }

        # 9 kind, including 5 IAE kind
        for kind in CompanyKind:
            JobApplicationFactory(
                **job_application_kwargs,
                to_company__kind=kind,
            )

        # +1 IAE kind acceptepd job application
        JobApplicationFactory(
            **job_application_kwargs,
            to_company__kind=CompanyKind.EI,
            was_hired=True,
        )

        call_command("anonymize_jobseekers", wet_run=True)

        anonymized_job_seeker_counts = AnonymizedJobSeeker.objects.values(
            "count_total_applications", "count_IAE_applications", "count_accepted_applications"
        )
        assert list(anonymized_job_seeker_counts) == [
            {
                "count_total_applications": 10,
                "count_IAE_applications": 6,
                "count_accepted_applications": 1,
            }
        ]

    def test_archive_jobseeker_with_approval(self, snapshot):
        kwargs = {
            "start_at": datetime.date(2020, 1, 18),
            "end_at": datetime.date(2023, 1, 18),
            "user__date_joined": timezone.make_aware(datetime.datetime(2020, 1, 15)),
            "user__notified_days_ago": 30,
            "user__for_snapshot": True,
        }

        # one stand alone approval without job applications
        ApprovalFactory(
            for_snapshot=True,
            origin_sender_kind=SenderKind.EMPLOYER,
            origin_siae_kind=CompanyKind.EA,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.MSA,
            **kwargs,
            user__email="test@example.com",
            user__jobseeker_profile__nir="2857612352678",
            user__jobseeker_profile__asp_uid=uuid1(),
            user__public_id=uuid4(),
        )

        # approval with eligibility diag, prolongation, suspension, accepted job application and employee record
        approval_with_few_datas = ApprovalFactory(
            origin_sender_kind=SenderKind.PRESCRIBER,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.CCAS,
            origin_siae_kind=None,
            eligibility_diagnosis__expires_at=datetime.date(2023, 1, 17),
            **kwargs,
            user__email="test2@example.com",
            user__jobseeker_profile__nir="2857612352679",
            user__jobseeker_profile__asp_uid=uuid1(),
            user__public_id=uuid4(),
        )
        ProlongationFactory(approval=approval_with_few_datas, for_snapshot=True, start_at=datetime.date(2022, 5, 17))
        SuspensionFactory(
            approval=approval_with_few_datas, start_at=datetime.date(2020, 5, 17), end_at=datetime.date(2020, 6, 10)
        )
        EmployeeRecordFactory(
            job_application__job_seeker=approval_with_few_datas.user,
            job_application__approval=approval_with_few_datas,
            job_application__eligibility_diagnosis=approval_with_few_datas.eligibility_diagnosis,
            job_application__created_at=timezone.make_aware(datetime.datetime(2023, 2, 16)),
            job_application__processed_at=timezone.make_aware(datetime.datetime(2023, 2, 16)),
            job_application__to_company__department=76,
            job_application__to_company__naf="4567A",
            job_application__to_company__kind=CompanyKind.EI,
            job_application__state=JobApplicationState.ACCEPTED,
            job_application__hiring_start_at=datetime.date(2023, 2, 2),
        )

        # approval with 3 prolongations, 2 suspensions and 2 job applications
        approval_with_lot_of_datas = ApprovalFactory(
            origin=Origin.ADMIN,
            origin_siae_kind=CompanyKind.EA,
            origin_sender_kind=SenderKind.EMPLOYER,
            eligibility_diagnosis__expires_at=datetime.date(2023, 1, 17),
            **kwargs,
            user__email="test3@example.com",
            user__jobseeker_profile__nir="2857612352670",
            user__jobseeker_profile__asp_uid=uuid1(),
            user__public_id=uuid4(),
        )
        for start_at in [datetime.date(2022, 5, 17), datetime.date(2022, 7, 16), datetime.date(2022, 9, 16)]:
            ProlongationFactory(
                approval=approval_with_lot_of_datas,
                start_at=start_at,
            )
        for start_at, end_at in [
            (datetime.date(2020, 5, 17), datetime.date(2020, 5, 20)),
            (datetime.date(2020, 9, 17), datetime.date(2020, 9, 20)),
        ]:
            SuspensionFactory(
                approval=approval_with_lot_of_datas,
                start_at=start_at,
                end_at=end_at,
            )
        for state in [JobApplicationState.ACCEPTED, JobApplicationState.NEW]:
            JobApplicationFactory(
                job_seeker=approval_with_lot_of_datas.user,
                approval=approval_with_lot_of_datas,
                eligibility_diagnosis=approval_with_lot_of_datas.eligibility_diagnosis,
                created_at=timezone.make_aware(datetime.datetime(2023, 1, 16)),
                processed_at=timezone.make_aware(datetime.datetime(2023, 1, 16))
                if state == JobApplicationState.ACCEPTED
                else None,
                to_company__department=76,
                to_company__naf="4567A",
                to_company__kind=CompanyKind.EI,
                state=state,
                hiring_start_at=datetime.date(2023, 3, 2),
            )

        call_command("anonymize_jobseekers", wet_run=True)

        assert not Approval.objects.exists()

        assert get_fields_list_for_snapshot(AnonymizedApproval) == snapshot(name="anonymized_approval")
        assert get_fields_list_for_snapshot(AnonymizedApplication) == snapshot(name="anonymized_application")

    def test_archive_jobseeker_with_several_approvals(self, snapshot):
        jobseeker = JobSeekerFactory(
            date_joined=timezone.make_aware(datetime.datetime(2019, 4, 18)),
            notified_days_ago=30,
            for_snapshot=True,
        )
        for start_at in [datetime.date(2019, 4, 18), datetime.date(2021, 5, 17)]:
            ApprovalFactory(
                user=jobseeker,
                start_at=start_at,
                end_at=start_at + relativedelta(years=2),
                eligibility_diagnosis__expires_at=datetime.date(2023, 1, 18),
            )

        call_command("anonymize_jobseekers", wet_run=True)

        assert not Approval.objects.exists()
        assert AnonymizedApproval.objects.count() == 2
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")

    def test_archive_jobseeker_with_eligibility_diagnosis(self, snapshot):
        kwargs = {
            "job_seeker__date_joined": timezone.make_aware(datetime.datetime(2020, 2, 16)),
            "job_seeker__notified_days_ago": DAYS_OF_GRACE,
        }
        # IAE Diagnosis from employer with approval
        iae_diagnosis_from_employer_with_approval = IAEEligibilityDiagnosisFactory(
            created_at=timezone.make_aware(datetime.datetime(2020, 2, 16, 0, 0, 0)),
            from_employer=True,
            author_siae__kind=CompanyKind.ACI,
            job_seeker__post_code="76160",
            job_seeker__jobseeker_profile__birthdate=datetime.date(1985, 6, 8),
            job_seeker__jobseeker_profile__nir="2857612352678",
            job_seeker__title=Title.MME,
            criteria_kinds=[
                AdministrativeCriteriaKind.RSA,
                AdministrativeCriteriaKind.AAH,
                AdministrativeCriteriaKind.PM,
            ],
            **kwargs,
        )

        iae_diagnosis_from_employer_with_approval.selected_administrative_criteria.filter(
            administrative_criteria__kind="AAH"
        ).update(certified=True)

        JobApplicationFactory(
            job_seeker=iae_diagnosis_from_employer_with_approval.job_seeker,
            eligibility_diagnosis=iae_diagnosis_from_employer_with_approval,
            created_at=timezone.make_aware(datetime.datetime(2021, 5, 17)),
            with_approval=True,
            approval__start_at=datetime.date(2020, 4, 18),
            approval__end_at=datetime.date(2023, 4, 17),
        )

        # IAE Diagnosis from prescriber with several job applications
        iae_diagnosis_from_prescriber_with_several_job_applications = IAEEligibilityDiagnosisFactory(
            created_at=timezone.make_aware(datetime.datetime(2020, 5, 23, 0, 0, 0)),
            from_prescriber=True,
            job_seeker__post_code="14390",
            job_seeker__jobseeker_profile__birthdate=datetime.date(1980, 5, 5),
            job_seeker__jobseeker_profile__nir="1801461235267",
            job_seeker__title=Title.M,
            **kwargs,
        )
        for state in [JobApplicationState.ACCEPTED, JobApplicationState.POSTPONED]:
            JobApplicationFactory(
                job_seeker=iae_diagnosis_from_prescriber_with_several_job_applications.job_seeker,
                to_company__subject_to_iae_rules=True,
                eligibility_diagnosis=iae_diagnosis_from_prescriber_with_several_job_applications,
                created_at=timezone.make_aware(datetime.datetime(2021, 6, 17)),
                state=state,
            )
        # GEIQ Diagnosis from employer without job application
        GEIQEligibilityDiagnosisFactory(
            created_at=timezone.make_aware(datetime.datetime(2020, 9, 21, 0, 0, 0)),
            from_employer=True,
            job_seeker__post_code="56120",
            job_seeker__jobseeker_profile__birthdate=datetime.date(1956, 11, 10),
            job_seeker__jobseeker_profile__nir="1565612352678",
            job_seeker__title=Title.M,
            criteria_kinds=[
                AdministrativeCriteriaKind.RSA,
                AdministrativeCriteriaKind.RECONVERSION,
                AdministrativeCriteriaKind.PM,
            ],
            **kwargs,
        )

        call_command("anonymize_jobseekers", wet_run=True)

        assert not EligibilityDiagnosis.objects.exists()
        assert not GEIQEligibilityDiagnosis.objects.exists()
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")
        assert get_fields_list_for_snapshot(AnonymizedSIAEEligibilityDiagnosis) == snapshot(
            name="anonymized_iae_diagnosis"
        )
        assert get_fields_list_for_snapshot(AnonymizedGEIQEligibilityDiagnosis) == snapshot(
            name="anonymized_geiq_diagnosis"
        )

    def test_archive_jobseeker_with_several_eligibility_diagnoses(self, snapshot):
        jobseeker = JobSeekerFactory(
            date_joined=timezone.make_aware(datetime.datetime(2022, 11, 11)),
            notified_days_ago=30,
            for_snapshot=True,
        )

        for eligibility_factory in [
            IAEEligibilityDiagnosisFactory,
            IAEEligibilityDiagnosisFactory,
            GEIQEligibilityDiagnosisFactory,
        ]:
            eligibility_factory(
                job_seeker=jobseeker,
                from_prescriber=True,
                created_at=timezone.make_aware(datetime.datetime(2022, 11, 11)),
                expires_at=datetime.date(2023, 1, 18),
            )

        call_command("anonymize_jobseekers", wet_run=True)

        assert not EligibilityDiagnosis.objects.exists()
        assert not GEIQEligibilityDiagnosis.objects.exists()
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")
        assert get_fields_list_for_snapshot(AnonymizedSIAEEligibilityDiagnosis) == snapshot(
            name="anonymized_siae_eligibility_diagnoses"
        )
        assert get_fields_list_for_snapshot(AnonymizedGEIQEligibilityDiagnosis) == snapshot(
            name="anonymized_geiq_eligibility_diagnoses"
        )

    def test_archive_jobseeker_with_assignments(self):
        jobseeker = JobSeekerFactory(
            date_joined=timezone.make_aware(datetime.datetime(2022, 11, 11)), notified_days_ago=30
        )
        JobSeekerAssignmentFactory(job_seeker=jobseeker)

        call_command("anonymize_jobseekers", wet_run=True)

        assert not JobSeekerAssignment.objects.exists()

    def test_anonymized_at_is_the_first_day_of_the_month(self):
        job_application = JobApplicationFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY,
            job_seeker__notified_days_ago=30,
            created_at=timezone.now() - INACTIVITY_PERIOD,
            with_iae_eligibility_diagnosis=True,
            eligibility_diagnosis__expires_at=datetime.date(2023, 1, 18),
        )
        ApprovalFactory(
            for_snapshot=True,
            user=job_application.job_seeker,
            start_at=datetime.date(2020, 1, 18),
            end_at=datetime.date(2023, 1, 18),
        )
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker,
            from_prescriber=True,
            expires_at=datetime.date(2023, 1, 18),
        )

        call_command("anonymize_jobseekers", wet_run=True)

        for model in [
            AnonymizedJobSeeker,
            AnonymizedApplication,
            AnonymizedApproval,
            AnonymizedSIAEEligibilityDiagnosis,
            AnonymizedGEIQEligibilityDiagnosis,
        ]:
            obj = model.objects.get()
            assert obj.anonymized_at == timezone.localdate().replace(day=1)


class TestNotifyInactiveProfessionalsManagementCommand:
    def test_dry_run(self, django_capture_on_commit_callbacks, mailoutbox):
        EmployerFactory(last_login_days_ago=DAYS_OF_INACTIVITY)
        PrescriberFactory(last_login_days_ago=DAYS_OF_INACTIVITY)
        LaborInspectorFactory(last_login_days_ago=DAYS_OF_INACTIVITY)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_professionals")

        assert not mailoutbox
        assert not User.objects.filter(upcoming_deletion_notified_at__isnull=False)

    def test_notify_batch_size(self):
        factory = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory])
        factory.create_batch(3, last_login_days_ago=DAYS_OF_INACTIVITY)

        call_command("notify_inactive_professionals", batch_size=2, wet_run=True)

        assert User.objects.filter(upcoming_deletion_notified_at__isnull=True).count() == 1
        assert User.objects.exclude(upcoming_deletion_notified_at__isnull=True).count() == 2

    def test_professionals_not_to_be_notified(self, django_capture_on_commit_callbacks, caplog, mailoutbox):
        # professional_soon_without_recent_activity
        EmployerFactory(last_login_days_ago=DAYS_OF_INACTIVITY - 1)
        # professional_never_logged_in
        PrescriberFactory()
        # professional_without_recent_activity_already_notified
        notified_professional = LaborInspectorFactory(last_login_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_professionals", wet_run=True)

        assert (
            not User.objects.exclude(id=notified_professional.id)
            .filter(upcoming_deletion_notified_at__isnull=False)
            .exists()
        )
        assert not mailoutbox
        assert "Notified inactive professionals without recent activity: 0" in caplog.messages

    @pytest.mark.parametrize(
        "factory_kwargs",
        [
            pytest.param({"last_login_days_ago": DAYS_OF_INACTIVITY}, id="professional_without_recent_activity"),
            pytest.param(
                {"is_active": False, "last_login_days_ago": DAYS_OF_INACTIVITY},
                id="deactivated_professional_without_recent_activity",
            ),
        ],
    )
    def test_notify_inactive_professionals(
        self,
        factory_kwargs,
        django_capture_on_commit_callbacks,
        caplog,
        mailoutbox,
        snapshot,
    ):
        factory = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory])
        user = factory(
            for_snapshot=True,
            first_name="Micheline",
            last_name="Dubois",
            email="micheline.dubois@example.com",
            **factory_kwargs,
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_professionals", wet_run=True)

        updated_user = User.objects.get()
        assert updated_user.upcoming_deletion_notified_at is not None

        assert "Notified inactive professionals without recent activity: 1" in caplog.messages

        if user.is_active:
            [mail] = mailoutbox
            assert [user.email] == mail.to
            assert mail.subject == snapshot(name="inactive_professional_email_subject")
            fmt_inactivity_since = (timezone.localdate() - INACTIVITY_PERIOD).strftime("%d/%m/%Y")
            fmt_end_of_grace = (timezone.localdate(user.upcoming_deletion_notified_at) + GRACE_PERIOD).strftime(
                "%d/%m/%Y"
            )
            body = mail.body.replace(fmt_inactivity_since, "XX/XX/XXXX").replace(fmt_end_of_grace, "YY/YY/YYYY")
            assert body == snapshot(name="inactive_professional_email_body")
        else:
            assert not mailoutbox

    def test_excluded_users_kind(
        self,
    ):
        JobSeekerFactory(last_login_days_ago=DAYS_OF_INACTIVITY)
        ItouStaffFactory(last_login_days_ago=DAYS_OF_INACTIVITY)

        call_command("notify_inactive_professionals", wet_run=True)

        assert not User.objects.filter(upcoming_deletion_notified_at__isnull=False)


class TestAnonymizeProfessionalManagementCommand:
    @pytest.mark.parametrize(
        "suspended,expected_message",
        [
            (True, "Anonymizing professionals is suspended, exiting command"),
            (False, "Start anonymizing professionals"),
        ],
    )
    def test_suspend_command_setting(self, settings, suspended, expected_message, caplog):
        EmployerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31)

        settings.SUSPEND_ANONYMIZE_PROFESSIONALS = suspended
        call_command("anonymize_professionals", wet_run=True)

        assert User.objects.exists() is suspended
        assert expected_message in caplog.messages

    def test_reset_notified_professional_dry_run(self):
        for factory in [EmployerFactory, PrescriberFactory, LaborInspectorFactory]:
            factory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now())

        call_command("anonymize_professionals")

        assert not User.objects.filter(upcoming_deletion_notified_at__isnull=True).exists()

    def test_reset_notified_professional(self):
        # professionals who never logged in
        never_logged_kwargs = {"joined_days_ago": DAYS_OF_INACTIVITY, "notified_days_ago": 1, "last_login": None}
        employer_never_logged = EmployerFactory(**never_logged_kwargs)
        prescriber_never_logged = PrescriberFactory(**never_logged_kwargs)
        labor_inspector_never_logged = LaborInspectorFactory(**never_logged_kwargs)

        # professionals who logged before being notified
        logged_the_day_before_notification_kwargs = {
            "joined_days_ago": DAYS_OF_INACTIVITY,
            "notified_days_ago": 1,
            "last_login": timezone.now() - relativedelta(days=1),
        }
        employer_logged_before_notification = EmployerFactory(**logged_the_day_before_notification_kwargs)
        prescriber_logged_before_notification = PrescriberFactory(**logged_the_day_before_notification_kwargs)
        labor_inspector_logged_before_notification = LaborInspectorFactory(**logged_the_day_before_notification_kwargs)

        # professionals who logged after being notified
        logged_after_notification_kwargs = {
            "joined_days_ago": DAYS_OF_INACTIVITY,
            "notified_days_ago": 1,
            "last_login": timezone.now(),
        }
        employer_logged_after_notification = EmployerFactory(**logged_after_notification_kwargs)
        prescriber_logged_after_notification = PrescriberFactory(**logged_after_notification_kwargs)
        labor_inspector_logged_after_notification = LaborInspectorFactory(**logged_after_notification_kwargs)

        call_command("anonymize_professionals", wet_run=True)

        assertQuerySetEqual(
            User.objects.filter(upcoming_deletion_notified_at__isnull=True),
            [
                employer_logged_after_notification,
                prescriber_logged_after_notification,
                labor_inspector_logged_after_notification,
            ],
            ordered=False,
        )
        assertQuerySetEqual(
            User.objects.filter(upcoming_deletion_notified_at__isnull=False),
            [
                employer_never_logged,
                prescriber_never_logged,
                labor_inspector_never_logged,
                employer_logged_before_notification,
                prescriber_logged_before_notification,
                labor_inspector_logged_before_notification,
            ],
            ordered=False,
        )

    def test_anonymize_professionals_dry_run(self, respx_mock):
        user = EmployerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31)
        call_command("anonymize_professionals")

        unmodified_user = User.objects.get()
        assert user == unmodified_user
        assert not AnonymizedProfessional.objects.exists()
        assert not respx_mock.calls.called

    def test_anonymize_professionals_batch_size(self, django_capture_on_commit_callbacks, respx_mock):
        EmployerFactory.create_batch(3, joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=31)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", batch_size=2, wet_run=True)

        assert AnonymizedProfessional.objects.count() == 2
        assert User.objects.filter(email__isnull=False).count() == 1
        assert respx_mock.calls.call_count == 2

    def test_excluded_users_when_anonymizing_professionals(self):
        employer_notified_still_in_grace_period = EmployerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=29
        )
        labor_inspector_with_recent_login = LaborInspectorFactory(
            joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30, last_login=timezone.now()
        )
        prescriber_never_notified = PrescriberFactory(joined_days_ago=DAYS_OF_INACTIVITY)
        jobseeker_notified = JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)
        itou_staff_notified = ItouStaffFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30)

        call_command("anonymize_professionals", wet_run=True)

        assertQuerySetEqual(
            User.objects.all(),
            [
                employer_notified_still_in_grace_period,
                labor_inspector_with_recent_login,
                prescriber_never_notified,
                jobseeker_notified,
                itou_staff_notified,
            ],
            ordered=False,
        )
        assert not AnonymizedProfessional.objects.exists()

    def test_anonymize_professionals_after_grace_period(
        self,
        django_capture_on_commit_callbacks,
        snapshot,
        caplog,
        respx_mock,
    ):
        def _create_professional(factory, has_related_objects, city):
            if city:
                kwargs = {
                    "is_active": True,
                    "user__is_active": True,
                    "user__phone": f"06060{city.post_codes[0]}",
                    "user__address_line_1": "8 rue du moulin",
                    "user__address_line_2": "Apt 4B",
                    "user__post_code": city.post_codes[0],
                    "user__city": "Test City",
                    "user__coords": city.coords,
                    "user__insee_city": city,
                    "user__email": f"test{city.post_codes[0]}@mail.com",
                    "user__with_verified_email": True,
                }
            else:
                kwargs = {
                    "is_active": False,
                    "user__is_active": False,
                    "user__phone": "",
                    "user__address_line_1": "",
                    "user__address_line_2": "",
                    "user__post_code": "",
                    "user__city": "",
                    "user__coords": None,
                    "user__insee_city": None,
                    "user__email": None,
                }
            org = factory(
                user__date_joined=timezone.make_aware(datetime.datetime(2023, 3, 17)),
                user__upcoming_deletion_notified_at=timezone.make_aware(datetime.datetime(2025, 1, 15, 10, 0, 0)),
                user__for_snapshot=True,
                user__public_id=uuid4(),
                user__title=Title.M,
                user__first_name="Not Yet Anonymized" if city else "Already Anonymized",
                user__last_name="Has Related Objects" if has_related_objects else "No Related Objects",
                **kwargs,
            )
            professional = org.user

            if has_related_objects:
                JobApplicationFactory(sender=professional)
            return professional

        anonymized_employer = _create_professional(CompanyMembershipFactory, True, None)
        prescriber = _create_professional(PrescriberMembershipFactory, True, create_city_saint_andre())
        to_delete_anonymized_labor_inspector = _create_professional(InstitutionMembershipFactory, False, None)
        to_delete_employer = _create_professional(CompanyMembershipFactory, False, create_city_geispolsheim())

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        users = (
            User.objects.filter(id__in=[anonymized_employer.id, prescriber.id])
            .order_by("id")
            .values_list(
                "is_active",
                "phone",
                "address_line_1",
                "address_line_2",
                "post_code",
                "city",
                "coords",
                "insee_city",
                "first_name",
                "last_name",
                "title",
            )
        )
        assert users == snapshot(name="anonymized_professionals_without_deletion")
        assert not EmailAddress.objects.exists()
        assert get_fields_list_for_snapshot(AnonymizedProfessional) == snapshot(
            name="deleted_anonymized_professionals"
        )
        assert not CompanyMembership.include_inactive.filter(user=to_delete_employer).exists()
        assert not InstitutionMembership.include_inactive.filter(user=to_delete_anonymized_labor_inspector).exists()
        assert CompanyMembership.include_inactive.filter(user=anonymized_employer, is_active=False).exists()
        assert PrescriberMembership.include_inactive.filter(user=prescriber, is_active=False).exists()

        assert respx_mock.calls.call_count == 2
        assert "Anonymized professionals after grace period, count: 4" in caplog.messages
        assert "Included in this count: 2 to delete, 2 to remove from contact" in caplog.messages

        remark = PkSupportRemark.objects.get(
            content_type=ContentType.objects.get_for_model(User), object_id=prescriber.id
        )
        assert remark.remark.endswith("- Désactivation/archivage de l'utilisateur")

    def test_anonymize_professional_had_membership_in_authorized_organization(
        self, django_capture_on_commit_callbacks, caplog, respx_mock
    ):
        membership = PrescriberMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2023, 3, 17)),
            user__upcoming_deletion_notified_at=timezone.make_aware(datetime.datetime(2025, 1, 15, 10, 0, 0)),
            organization__authorized=True,
        )
        prescriber = membership.user
        # The related object prevents deletion.
        job_application = JobApplicationFactory(
            sender=prescriber,
            with_iae_eligibility_diagnosis=True,
        )
        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)
        assert "Anonymized professionals after grace period, count: 1" in caplog.messages

        caplog.clear()
        # Related objects are deleted, the prescriber can be deleted.
        job_application.delete()
        job_application.eligibility_diagnosis.delete()
        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)
        assert "Anonymized professionals after grace period, count: 1" in caplog.messages
        assert respx_mock.calls.call_count == 1

        # Even though the prescriber membership was inactive because the first
        # anonymize_professional deactivated the user, it is still accounted
        # for when deleting the user account.
        anonymized_prescriber = AnonymizedProfessional.objects.get()
        assert anonymized_prescriber.had_memberships_in_authorized_organization is True

    @pytest.mark.parametrize("with_organization", [True, False])
    def test_anonymize_professional_with_job_seeker_assignment(
        self, with_organization, django_capture_on_commit_callbacks, caplog, respx_mock
    ):
        organization = PrescriberOrganizationFactory() if with_organization else None
        JobSeekerAssignmentFactory(
            prescriber__date_joined=timezone.make_aware(datetime.datetime(2023, 3, 17)),
            prescriber__upcoming_deletion_notified_at=timezone.make_aware(datetime.datetime(2025, 1, 15, 10, 0, 0)),
            prescriber_organization=organization,
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        assert "Anonymized professionals after grace period, count: 1" in caplog.messages

        # If the assignment beared an organization, nothing was really deleted in order to keep somewhere the link
        # between the job seeker and the organization
        assert JobSeekerAssignment.objects.exists() is with_organization

        # The previous assignment blocked the actual deletion, even if there was no organization…
        assert User.objects.filter(kind=UserKind.PRESCRIBER).exists()

        # …but running again the command deletes it for real, if there was no organization.
        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        assert caplog.messages.count("Anonymized professionals after grace period, count: 1") == 2
        assert User.objects.filter(kind=UserKind.PRESCRIBER).exists() is with_organization

    @pytest.mark.parametrize("is_active", [True, False])
    def test_anonymize_professionals_notification(
        self, is_active, django_capture_on_commit_callbacks, caplog, mailoutbox, snapshot, respx_mock
    ):
        factory = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory])
        factory(
            date_joined=timezone.make_aware(datetime.datetime(2023, 5, 17)),
            upcoming_deletion_notified_at=timezone.make_aware(datetime.datetime(2025, 6, 17)),
            is_active=is_active,
            for_snapshot=True,
            first_name="Micheline",
            last_name="Dubois",
            email="micheline.dubois@example.com",
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        if is_active:
            [mail] = mailoutbox
            assert mail.subject == snapshot(name="anonymized_professional_email_subject")
            assert mail.body == snapshot(name="anonymized_professional_email_body")
        else:
            assert mailoutbox == []
        assert respx_mock.calls.call_count == 1

    def test_anonymized_professionals_annotations(self, django_capture_on_commit_callbacks, snapshot):
        # authorized_prescriber_admin_membership
        PrescriberMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 2, 16)),
            user__notified_days_ago=31,
            organization__authorized=True,
        )
        # prescriber_membership
        PrescriberMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 3, 16)),
            user__notified_days_ago=31,
            organization__authorized=False,
            is_admin=False,
        )
        # disabled_prescriber_membership
        PrescriberMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 4, 16)),
            user__notified_days_ago=31,
            is_admin=False,
            is_active=False,
        )
        # company_admin_membership
        CompanyMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 5, 16)), user__notified_days_ago=31
        )
        # company_membership
        CompanyMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 6, 16)),
            user__notified_days_ago=31,
            is_admin=False,
        )
        # disabled_company_membership
        CompanyMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 7, 16)),
            user__notified_days_ago=31,
            is_admin=False,
            is_active=False,
        )
        # institution_admin_membership
        InstitutionMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 8, 16)),
            user__notified_days_ago=31,
            is_admin=True,
        )
        # institution_membership
        InstitutionMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 9, 16)),
            user__notified_days_ago=31,
            is_admin=False,
        )
        # disabled_institution_membership
        InstitutionMembershipFactory(
            user__date_joined=timezone.make_aware(datetime.datetime(2020, 10, 16)),
            user__notified_days_ago=31,
            is_admin=False,
            is_active=False,
        )

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        assert get_fields_list_for_snapshot(AnonymizedProfessional) == snapshot(
            name="anonymized_professionals_with_annotations"
        )

    def test_num_queries(self, snapshot):
        for pm in PrescriberMembershipFactory.create_batch(
            3, user__notified_days_ago=31, organization__authorized=True
        ):
            PrescriberMembershipFactory.create_batch(2, user=pm.user, organization__authorized=True)
        for em in CompanyMembershipFactory.create_batch(3, user__notified_days_ago=31):
            CompanyMembershipFactory.create_batch(2, user=em.user)
        for im in InstitutionMembershipFactory.create_batch(3, user__notified_days_ago=31):
            InstitutionMembershipFactory.create_batch(2, user=im.user)

        with assertSnapshotQueries(snapshot(name="anonymize_professionals_queries")):
            call_command("anonymize_professionals", wet_run=True)

    def test_anonymized_at_is_the_first_day_of_the_month(self):
        EmployerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=31,
        )

        call_command("anonymize_professionals", wet_run=True)

        anonymized_professional = AnonymizedProfessional.objects.get()
        assert anonymized_professional.anonymized_at == timezone.localdate().replace(day=1)


class TestAnonymizeCancelledApprovalsManagementCommand:
    @pytest.mark.parametrize("suspended", [True, False])
    def test_suspend_command_setting(self, settings, suspended, caplog):
        expiration_date = timezone.localdate() - EXPIRATION_PERIOD
        CancelledApprovalFactory(
            start_at=expiration_date - datetime.timedelta(days=1),
            end_at=expiration_date,
        )

        settings.SUSPEND_ANONYMIZE_CANCELLED_APPROVALS = suspended
        call_command("anonymize_cancelled_approvals", wet_run=True)

        assert CancelledApproval.objects.exists() is suspended
        assert ("Anonymizing cancelled approvals is suspended, exiting command" in caplog.messages) is suspended

    def test_dry_run(self):
        expiration_date = timezone.localdate() - EXPIRATION_PERIOD
        CancelledApprovalFactory(
            start_at=expiration_date - datetime.timedelta(days=1),
            end_at=expiration_date,
        )
        call_command("anonymize_cancelled_approvals")
        CancelledApproval.objects.get()
        assert not AnonymizedCancelledApproval.objects.exists()

    def test_anonymize_cancelled_approvals_content(self, snapshot):
        expiration_date = timezone.localdate() - EXPIRATION_PERIOD
        kwargs_list = [
            {
                "user_birthdate": datetime.date(1977, 7, 16),
                "user_nir": "277071456789012",
                "user_id_national_pe": "89012345",
                "origin_siae_kind": CompanyKind.EI,
            },
            {
                "user_birthdate": None,
                "user_nir": "",
                "user_id_national_pe": None,
                "origin_siae_kind": CompanyKind.EATT,
                "origin_sender_kind": UserKind.PRESCRIBER,
                "origin_prescriber_organization_kind": PrescriberOrganizationKind.CHRS,
            },
        ]
        for kwargs in kwargs_list:
            CancelledApprovalFactory(
                start_at=expiration_date - datetime.timedelta(days=1), end_at=expiration_date, **kwargs
            )

        call_command("anonymize_cancelled_approvals", wet_run=True)

        assert get_fields_list_for_snapshot(AnonymizedCancelledApproval) == snapshot(
            name="anonymized_cancelled_approval"
        )
        assert not CancelledApproval.objects.exists()

    def test_anonymize_cancelled_approvals_on_expiration_date(self):
        expiration_date = timezone.localdate() - EXPIRATION_PERIOD
        start_at = expiration_date - datetime.timedelta(days=30)

        # recently_expired_cancelled_approval
        CancelledApprovalFactory(start_at=start_at, end_at=expiration_date)

        # expiring_soon_cancelled_approval
        expected_cancelled_approval = CancelledApprovalFactory(
            start_at=start_at,
            end_at=expiration_date + datetime.timedelta(days=1),
        )

        call_command("anonymize_cancelled_approvals", wet_run=True)

        assertQuerySetEqual(CancelledApproval.objects.all(), [expected_cancelled_approval])
        assert AnonymizedCancelledApproval.objects.count() == 1

    def test_anonymized_at_is_the_first_day_of_the_month(self):
        expiration_date = timezone.localdate() - EXPIRATION_PERIOD
        start_at = expiration_date - datetime.timedelta(days=30)
        CancelledApprovalFactory(start_at=start_at, end_at=expiration_date)

        call_command("anonymize_cancelled_approvals", wet_run=True)

        anonymized_cancelled_approval = AnonymizedCancelledApproval.objects.get()
        assert anonymized_cancelled_approval.anonymized_at == timezone.localdate().replace(day=1)


class TestRemoveUnknownEmailsFromBrevoCommand:
    def test_remove_unknown_emails_from_brevo_dry_run(
        self, django_capture_on_commit_callbacks, mocker, caplog, respx_mock
    ):
        responses = [
            [
                {
                    "email": "test@email.com",
                    "modifiedAt": "2022-01-18T16:15:13.678Z",
                }
            ],
            [],
        ]

        mocker.patch("itou.utils.brevo.BrevoClient.list_contacts", side_effect=responses)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("remove_unknown_emails_from_brevo")

        assert respx_mock.calls.call_count == 0
        for msg in [
            "Found 1 emails to delete at offset 0",
            "[DRY RUN] Would delete contact: test@email.com",
            "No more contact to process at offset 1000",
            "Found 1 emails to delete",
        ]:
            assert msg in caplog.messages

    def test_remove_unknown_emails_from_brevo_with_offset(
        self, django_capture_on_commit_callbacks, caplog, respx_mock
    ):
        respx_mock.get(f"{settings.BREVO_API_URL}/contacts?limit=1000&offset=200&sort=asc").mock(
            return_value=httpx.Response(status_code=200, json={"contacts": []})
        )
        with django_capture_on_commit_callbacks(execute=True):
            call_command("remove_unknown_emails_from_brevo", wet_run=True, offset=200)

        assert respx_mock.calls.call_count == 1
        assert "No more contact to process at offset 200" in caplog.messages

    def test_remove_unknown_emails_from_brevo_exception(
        self, django_capture_on_commit_callbacks, mocker, caplog, respx_mock
    ):
        mocker.patch("itou.utils.brevo.BrevoClient.list_contacts", side_effect=MalformedResponseException)
        with django_capture_on_commit_callbacks(execute=True):
            call_command("remove_unknown_emails_from_brevo", wet_run=True)

        assert respx_mock.calls.call_count == 0
        assert "Error fetching contacts at offset 0: Malformed response" in caplog.messages

    @pytest.mark.parametrize("verbosity", [1, 2])
    def test_remove_unknown_emails_from_brevo(
        self, verbosity, django_capture_on_commit_callbacks, mocker, caplog, respx_mock
    ):
        known_users = EmployerFactory.create_batch(2)
        two_years_ago = timezone.now() - relativedelta(years=2) - datetime.timedelta(minutes=1)
        almost_two_years_ago = two_years_ago + datetime.timedelta(days=1)
        two_years_ago_fmt = two_years_ago.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        almost_two_years_ago_fmt = almost_two_years_ago.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        responses = [
            [
                {
                    "email": known_users[0].email,
                    "createdAt": two_years_ago_fmt,
                    "modifiedAt": almost_two_years_ago_fmt,
                },
                {
                    "email": known_users[1].email,
                    "createdAt": two_years_ago_fmt,
                    "modifiedAt": two_years_ago_fmt,
                },
                {
                    "email": "recently.modified@email.com",
                    "createdAt": two_years_ago_fmt,
                    "modifiedAt": almost_two_years_ago_fmt,
                },
                {
                    "email": "modified.two.years.ago@email.com",
                    "createdAt": two_years_ago_fmt,
                    "modifiedAt": two_years_ago_fmt,
                },
            ],
            [
                {
                    "email": "created.two.years.ago@email.com",
                    "createdAt": two_years_ago_fmt,
                },
                {
                    "email": "no.created_at.key@email.com",
                    "modifiedAt": almost_two_years_ago_fmt,
                },
                {
                    "email": "dummy@email.com",
                },
            ],
            [],
        ]

        mocker.patch("itou.utils.brevo.BrevoClient.list_contacts", side_effect=responses)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("remove_unknown_emails_from_brevo", wet_run=True, verbosity=verbosity)

        assert respx_mock.calls.call_count == 2

        for msg in [
            "Found 1 emails to delete at offset 0",
            "Found 1 emails to delete at offset 1000",
            "No more contact to process at offset 2000",
            "Found 2 emails to delete",
        ]:
            assert msg in caplog.messages
        for msg in [
            "Deleting contact: modified.two.years.ago@email.com",
            "Deleting contact: created.two.years.ago@email.com",
        ]:
            assert (msg in caplog.messages) == (verbosity > 1)
