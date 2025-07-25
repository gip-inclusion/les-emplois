import datetime
import random
import re
from unittest.mock import patch
from uuid import uuid1, uuid4

import httpx
import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.approvals.enums import Origin
from itou.approvals.models import Approval, CancelledApproval
from itou.archive.models import (
    AnonymizedApplication,
    AnonymizedApproval,
    AnonymizedCancelledApproval,
    AnonymizedGEIQEligibilityDiagnosis,
    AnonymizedJobSeeker,
    AnonymizedProfessional,
    AnonymizedSIAEEligibilityDiagnosis,
)
from itou.companies.enums import CompanyKind, ContractType
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
from itou.jobs.models import Appellation, Rome
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import Title, UserKind
from itou.users.models import User
from itou.utils.constants import DAYS_OF_GRACE, DAYS_OF_INACTIVITY, EXPIRATION_PERIOD, GRACE_PERIOD, INACTIVITY_PERIOD
from tests.approvals.factories import ApprovalFactory, CancelledApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.files.factories import FileFactory
from tests.gps.factories import FollowUpGroupFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import assertSnapshotQueries


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


@pytest.fixture(name="city")
def city_fixture():
    return create_city_saint_andre()


def get_fields_list_for_snapshot(model):
    exclude = {"id", "anonymized_at"}
    fields = [f.name for f in model._meta.get_fields() if f.concrete and f.name not in exclude]
    return list(model.objects.values(*fields))


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
            call_command("notify_inactive_jobseekers", wet_run=True)

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

    def test_notify_inactive_jobseekers_on_approval_expiration_date(self):
        inactivity_threshold = timezone.localdate() - INACTIVITY_PERIOD
        long_time_ago = timezone.now() - relativedelta(years=3)
        approval_kwargs = {
            "user__joined_days_ago": DAYS_OF_INACTIVITY,
            "eligibility_diagnosis__updated_at": long_time_ago,
            "eligibility_diagnosis__expires_at": long_time_ago.date(),
            "start_at": long_time_ago.date(),
            "updated_at": long_time_ago,
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
        long_time_ago = timezone.now() - relativedelta(years=3)
        eligibility_kwargs = {
            "job_seeker__joined_days_ago": DAYS_OF_INACTIVITY,
            "from_prescriber": True,
            "updated_at": long_time_ago,
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


class TestAnonymizeJobseekersManagementCommand:
    @pytest.mark.parametrize("suspended", [True, False])
    @pytest.mark.parametrize("wet_run", [True, False])
    def test_suspend_command_setting(self, settings, suspended, wet_run, caplog, snapshot):
        settings.SUSPEND_ANONYMIZE_JOBSEEKERS = suspended
        call_command("anonymize_jobseekers", wet_run=wet_run)
        assert caplog.messages[0] == snapshot(name="suspend_anonymize_jobseekers_command_log")

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
                lambda: JobSeekerFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY,
                    notified_days_ago=1,
                ),
                lambda jobseeker: ApprovalFactory(
                    user=jobseeker,
                    expired=True,
                    updated_at=timezone.now() - relativedelta(years=3),
                    eligibility_diagnosis__updated_at=timezone.now() - relativedelta(years=3),
                ),
                False,
                id="notified_jobseeker_with_expired_approval_not_recently_updated",
            ),
            pytest.param(
                lambda: JobSeekerFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY,
                    notified_days_ago=1,
                ),
                lambda jobseeker: ApprovalFactory(
                    user=jobseeker,
                    expired=True,
                    updated_at=timezone.now(),
                    eligibility_diagnosis__updated_at=timezone.now() - relativedelta(years=3),
                ),
                True,
                id="notified_jobseeker_with_expired_approval_recently_updated",
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
    def test_reset_notified_jobseekers_with_recent_activity(
        self, factory, related_object_factory, notification_reset, respx_mock
    ):
        user = factory()
        if related_object_factory:
            related_object_factory(user)

        call_command("anonymize_jobseekers", wet_run=True)

        user.refresh_from_db()
        assert (user.upcoming_deletion_notified_at is None) == notification_reset
        assert not respx_mock.calls.called

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
    def test_exclude_users_when_archiving(self, user_factory, respx_mock):
        user = user_factory()
        call_command("anonymize_jobseekers", wet_run=True)

        expected_user = User.objects.get()
        assert user == expected_user
        assert not AnonymizedJobSeeker.objects.exists()
        assert not respx_mock.calls.called

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
        self,
        kwargs,
        jobapplication_kwargs_list,
        django_capture_on_commit_callbacks,
        caplog,
        mailoutbox,
        snapshot,
        respx_mock,
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
            call_command("anonymize_jobseekers", wet_run=True)

        assert not User.objects.filter(id=jobseeker.id).exists()
        assert not JobApplication.objects.filter(job_seeker=jobseeker).exists()

        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="archived_jobseeker")

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
        jobseeker = JobSeekerFactory(
            joined_days_ago=365,
            notified_days_ago=31,
        )
        FollowUpGroupFactory(beneficiary=jobseeker, memberships=2, updated_at=timezone.now() - INACTIVITY_PERIOD)

        assert FollowUpGroup.objects.exists()
        assert FollowUpGroupMembership.objects.exists()

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

        assert not User.objects.filter(id=jobseeker.id).exists()
        assert not FollowUpGroup.objects.exists()
        assert not FollowUpGroupMembership.objects.exists()
        assert AnonymizedJobSeeker.objects.exists()
        assert respx_mock.calls.call_count == 1

    def test_archive_inactive_jobseekers_with_file(self, django_capture_on_commit_callbacks, respx_mock):
        resume_file = FileFactory()
        JobApplicationFactory(
            job_seeker__notified_days_ago=31,
            job_seeker__date_joined=timezone.make_aware(datetime.datetime(2023, 10, 30, 0, 0)),
            approval=None,
            eligibility_diagnosis=None,
            geiq_eligibility_diagnosis=None,
            updated_at=timezone.now() - INACTIVITY_PERIOD,
            resume=resume_file,
        )
        other_files = [FileFactory(), JobApplicationFactory().resume]

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_jobseekers", wet_run=True)

        assertQuerySetEqual(File.objects.all(), other_files, ordered=False)
        assert respx_mock.calls.call_count == 1

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
                    "to_company__romes": ["N1101"],
                    "hiring_start_at": datetime.date(2025, 2, 2),
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
        respx_mock,
    ):
        job_seeker = JobSeekerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=30,
            jobseeker_profile__birthdate=datetime.date(1978, 5, 17),
            post_code="76160",
            for_snapshot=True,
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
            call_command("anonymize_jobseekers", wet_run=True)

        assert get_fields_list_for_snapshot(AnonymizedApplication) == snapshot(name="archived_application")
        assert not JobApplication.objects.filter(id=job_application.id).exists()
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")
        assert "Anonymized job applications after grace period, count: 1" in caplog.messages

        assert respx_mock.calls.call_count == 1

    def test_archive_jobseeker_with_approval(self, snapshot):
        job_seeker_kwargs = {
            "user__joined_days_ago": DAYS_OF_INACTIVITY,
            "user__notified_days_ago": 30,
            "user__for_snapshot": True,
        }

        # one stand alone approval without job applications
        ApprovalFactory(
            for_snapshot=True,
            origin_sender_kind=SenderKind.EMPLOYER,
            origin_siae_kind=CompanyKind.EA,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.MSA,
            start_at=datetime.date(2020, 1, 18),
            end_at=datetime.date(2023, 1, 18),
            **job_seeker_kwargs,
            user__email="test@example.com",
            user__jobseeker_profile__nir="2857612352678",
            user__jobseeker_profile__asp_uid=uuid1(),
            user__public_id=uuid4(),
        )

        # approval with eligibility diag, prolongation, suspension and accepted job application
        approval_with_few_datas = ApprovalFactory(
            origin_sender_kind=SenderKind.PRESCRIBER,
            origin_prescriber_organization_kind=PrescriberOrganizationKind.CCAS,
            origin_siae_kind=None,
            start_at=datetime.date(2020, 1, 18),
            end_at=datetime.date(2023, 1, 17),
            eligibility_diagnosis__updated_at=timezone.now() - INACTIVITY_PERIOD,
            **job_seeker_kwargs,
            user__email="test2@example.com",
            user__jobseeker_profile__nir="2857612352679",
            user__jobseeker_profile__asp_uid=uuid1(),
            user__public_id=uuid4(),
        )
        ProlongationFactory(approval=approval_with_few_datas, for_snapshot=True, start_at=datetime.date(2022, 5, 17))
        SuspensionFactory(
            approval=approval_with_few_datas, start_at=datetime.date(2020, 5, 17), end_at=datetime.date(2020, 6, 10)
        )
        JobApplicationFactory(
            job_seeker=approval_with_few_datas.user,
            approval=approval_with_few_datas,
            eligibility_diagnosis=approval_with_few_datas.eligibility_diagnosis,
            updated_at=timezone.now() - relativedelta(years=3),
            to_company__department=76,
            to_company__naf="4567A",
            state=JobApplicationState.ACCEPTED,
        )

        # approval with 3 prolongations, 2 suspensions and 2 job applications
        approval_with_lot_of_datas = ApprovalFactory(
            origin=Origin.ADMIN,
            origin_siae_kind=CompanyKind.EA,
            origin_sender_kind=SenderKind.EMPLOYER,
            start_at=datetime.date(2020, 1, 18),
            end_at=datetime.date(2023, 1, 17),
            eligibility_diagnosis__updated_at=timezone.now() - relativedelta(years=3),
            **job_seeker_kwargs,
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
                updated_at=timezone.now() - relativedelta(years=3),
                to_company__department=76,
                to_company__naf="4567A",
                state=state,
            )

        Approval.objects.update(updated_at=timezone.now() - relativedelta(years=3))

        call_command("anonymize_jobseekers", wet_run=True)

        assert not Approval.objects.exists()

        assert get_fields_list_for_snapshot(AnonymizedApproval) == snapshot(name="anonymized_approval")
        assert get_fields_list_for_snapshot(AnonymizedApplication) == snapshot(name="anonymized_application")

    def test_archive_jobseeker_with_several_approvals(self, snapshot):
        jobseeker = JobSeekerFactory(
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=30,
            for_snapshot=True,
        )
        for start_at in [datetime.date(2019, 4, 18), datetime.date(2021, 5, 17)]:
            ApprovalFactory(
                user=jobseeker,
                start_at=start_at,
                end_at=start_at + relativedelta(years=2),
                eligibility_diagnosis__updated_at=timezone.now() - relativedelta(years=3),
            )

        jobseeker.approvals.update(updated_at=timezone.now() - relativedelta(years=3))

        call_command("anonymize_jobseekers", wet_run=True)

        assert not Approval.objects.exists()
        assert AnonymizedApproval.objects.count() == 2
        assert get_fields_list_for_snapshot(AnonymizedJobSeeker) == snapshot(name="anonymized_jobseeker")

    def test_archive_jobseeker_with_eligibility_diagnosis(self, snapshot):
        kwargs = {
            "updated_at": timezone.now() - relativedelta(years=3),
            "job_seeker__joined_days_ago": DAYS_OF_INACTIVITY,
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
            updated_at=timezone.now() - relativedelta(years=3),
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
                eligibility_diagnosis=iae_diagnosis_from_prescriber_with_several_job_applications,
                updated_at=timezone.now() - relativedelta(years=3),
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

        Approval.objects.update(updated_at=timezone.now() - relativedelta(years=3))

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
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=30,
            for_snapshot=True,
        )

        for eligibility_factory in [
            IAEEligibilityDiagnosisFactory,
            IAEEligibilityDiagnosisFactory,
            GEIQEligibilityDiagnosisFactory,
        ]:
            eligibility_factory(
                job_seeker=jobseeker, from_prescriber=True, updated_at=timezone.now() - relativedelta(years=3)
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

    def test_anonymized_at_is_the_first_day_of_the_month(self):
        job_application = JobApplicationFactory(
            job_seeker__joined_days_ago=DAYS_OF_INACTIVITY,
            job_seeker__notified_days_ago=30,
            updated_at=timezone.now() - INACTIVITY_PERIOD,
            eligibility_diagnosis__updated_at=timezone.now() - INACTIVITY_PERIOD,
        )
        ApprovalFactory(
            for_snapshot=True,
            user=job_application.job_seeker,
            start_at=datetime.date(2020, 1, 18),
            end_at=datetime.date(2023, 1, 18),
            updated_at=timezone.now() - INACTIVITY_PERIOD,
        )
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker, from_prescriber=True, updated_at=timezone.now() - INACTIVITY_PERIOD
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

    @pytest.mark.parametrize(
        "factory_kwargs,expected_notification",
        [
            pytest.param({"last_login_days_ago": DAYS_OF_INACTIVITY}, True, id="professional_without_recent_activity"),
            pytest.param(
                {"is_active": False, "last_login_days_ago": DAYS_OF_INACTIVITY},
                True,
                id="deactivated_professional_without_recent_activity",
            ),
            pytest.param(
                {"last_login_days_ago": DAYS_OF_INACTIVITY - 1}, False, id="professional_soon_without_recent_activity"
            ),
            pytest.param({}, False, id="professional_never_logged_in"),
            pytest.param(
                {"last_login_days_ago": DAYS_OF_INACTIVITY, "notified_days_ago": 1},
                False,
                id="professional_without_recent_activity_already_notified",
            ),
        ],
    )
    def test_notify_inactive_professionals(
        self,
        factory_kwargs,
        expected_notification,
        django_capture_on_commit_callbacks,
        caplog,
        mailoutbox,
        snapshot,
    ):
        factory = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory])
        user = factory(for_snapshot=True, first_name="Micheline", last_name="Dubois", **factory_kwargs)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("notify_inactive_professionals", wet_run=True)

        updated_user = User.objects.get()
        assert (
            updated_user.upcoming_deletion_notified_at is not None
        ) == expected_notification or user.upcoming_deletion_notified_at is not None

        if expected_notification:
            assert "Notified inactive professionals without recent activity: 1" in caplog.messages

            if user.is_active:
                [mail] = mailoutbox
                assert [user.email] == mail.to
                assert mail.subject == snapshot(name="inactive_professional_email_subject")
                fmt_last_login = timezone.localdate(user.last_login).strftime("%d/%m/%Y")
                fmt_end_of_grace = (timezone.localdate(user.upcoming_deletion_notified_at) + GRACE_PERIOD).strftime(
                    "%d/%m/%Y"
                )
                body = mail.body.replace(fmt_last_login, "XX/XX/XXXX").replace(fmt_end_of_grace, "YY/YY/YYYY")
                assert body == snapshot(name="inactive_professional_email_body")
            else:
                assert not mailoutbox

        else:
            assert not mailoutbox
            assert "Notified inactive professionals without recent activity: 0" in caplog.messages

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
        settings.SUSPEND_ANONYMIZE_PROFESSIONALS = suspended
        call_command("anonymize_professionals", wet_run=True)
        assert expected_message in caplog.messages

    @pytest.mark.parametrize("factory", [EmployerFactory, PrescriberFactory, LaborInspectorFactory])
    def test_reset_notified_professional_dry_run(self, factory):
        user = factory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=timezone.now())
        call_command("anonymize_professionals")

        user.refresh_from_db()
        assert user.upcoming_deletion_notified_at is not None

    @pytest.mark.parametrize("factory", [EmployerFactory, PrescriberFactory, LaborInspectorFactory])
    @pytest.mark.parametrize(
        "last_login, expected",
        [(None, False), (timezone.now() - relativedelta(days=1), False), (timezone.now(), True)],
    )
    def test_reset_notified_professional(self, factory, last_login, expected):
        user = factory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=1, last_login=last_login)
        call_command("anonymize_professionals", wet_run=True)

        user.refresh_from_db()
        assert (user.upcoming_deletion_notified_at is None) == expected

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

    @pytest.mark.parametrize(
        "factory",
        [
            pytest.param(
                lambda: EmployerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=29),
                id="employer_notified_still_in_grace_period",
            ),
            pytest.param(
                lambda: LaborInspectorFactory(
                    joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30, last_login=timezone.now()
                ),
                id="labor_inspector_with_recent_login",
            ),
            pytest.param(
                lambda: PrescriberFactory(joined_days_ago=DAYS_OF_INACTIVITY),
                id="prescriber_never_notified",
            ),
            pytest.param(
                lambda: JobSeekerFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30),
                id="jobseeker_notified",
            ),
            pytest.param(
                lambda: ItouStaffFactory(joined_days_ago=DAYS_OF_INACTIVITY, notified_days_ago=30),
                id="itou_staff_notified",
            ),
        ],
    )
    def test_excluded_users_when_anonymizing_professionals(self, factory):
        user = factory()
        call_command("anonymize_professionals", wet_run=True)

        expected_user = User.objects.get()
        assert user == expected_user
        assert not AnonymizedProfessional.objects.exists()

    @pytest.mark.parametrize(
        "factory,has_related_objects,is_anonymized",
        [
            pytest.param(CompanyMembershipFactory, True, True, id="has_related_objects_and_is_anonymized"),
            pytest.param(PrescriberMembershipFactory, True, False, id="has_related_objects_and_not_anonymized"),
            pytest.param(InstitutionMembershipFactory, False, True, id="no_related_objects_and_is_anonymized"),
            pytest.param(CompanyMembershipFactory, False, False, id="no_related_objects_and_not_anonymized"),
        ],
    )
    @freeze_time("2025-02-15")
    def test_anonymize_professionals_after_grace_period(
        self,
        factory,
        has_related_objects,
        is_anonymized,
        city,
        django_capture_on_commit_callbacks,
        snapshot,
        caplog,
        respx_mock,
    ):
        org = factory(
            user__joined_days_ago=DAYS_OF_INACTIVITY,
            user__notified_days_ago=31,
            user__for_snapshot=True,
            user__address_line_1="8 rue du moulin",
            user__address_line_2="Apt 4B",
            user__post_code=city.post_codes[0],
            user__city="Test City",
            user__coords=city.coords,
            user__insee_city=city,
            user__email=None if is_anonymized else "test@mail.com",
        )
        professional = org.user

        if has_related_objects:
            JobApplicationFactory(sender=professional)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("anonymize_professionals", wet_run=True)

        # User should be deleted
        if not has_related_objects:
            assert not User.objects.filter(id=professional.id).exists()
            assert get_fields_list_for_snapshot(AnonymizedProfessional) == snapshot(name="anonymized_professional")
            assert respx_mock.calls.call_count == 0 if is_anonymized else 1
            for model in (CompanyMembership, PrescriberMembership, InstitutionMembership):
                assert not model.objects.filter(is_active=True, user_id=professional.id).exists()

        # User is not deletable because of related objects and should be anonymized
        elif not is_anonymized:
            user = User.objects.filter(id=professional.id).values(
                "is_active",
                "password",
                "phone",
                "address_line_1",
                "address_line_2",
                "post_code",
                "city",
                "coords",
                "insee_city",
                "upcoming_deletion_notified_at",
                "first_name",
                "last_name",
            )
            assert user == snapshot(name="user_values_after_anonymization")
            assert not AnonymizedProfessional.objects.exists()
            assert respx_mock.calls.call_count == 1
            for model in (CompanyMembership, PrescriberMembership, InstitutionMembership):
                assert not model.objects.filter(is_active=True, user_id=professional.id).exists()

        # User is not deletable because of related objects and is already anonymized
        else:
            professional.refresh_from_db()
            assert professional == User.objects.filter(id=professional.id).first()
            assert not AnonymizedProfessional.objects.exists()
            assert not respx_mock.calls.called

        # Check logs
        assert "Anonymized professionals after grace period, count: 1" in caplog.messages
        assert (
            f"Included in this count: {0 if has_related_objects else 1} to delete, {0 if is_anonymized else 1}"
            " to remove from contact"
        )

    @pytest.mark.parametrize("is_active", [True, False])
    @freeze_time("2025-02-15")
    def test_anonymize_professionals_notification(
        self, is_active, django_capture_on_commit_callbacks, caplog, mailoutbox, snapshot, respx_mock
    ):
        factory = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory])
        factory(
            joined_days_ago=DAYS_OF_INACTIVITY,
            notified_days_ago=31,
            is_active=is_active,
            for_snapshot=True,
            first_name="Micheline",
            last_name="Dubois",
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

    @pytest.mark.parametrize(
        "factory",
        [
            pytest.param(
                lambda: PrescriberMembershipFactory(user__notified_days_ago=31, organization__authorized=True),
                id="authorized_prescriber_admin_membership",
            ),
            pytest.param(
                lambda: PrescriberMembershipFactory(
                    user__notified_days_ago=31, organization__authorized=False, is_admin=False
                ),
                id="prescriber_membership",
            ),
            pytest.param(
                lambda: PrescriberMembershipFactory(user__notified_days_ago=31, is_active=False),
                id="disabled_prescriber_membership",
            ),
            pytest.param(lambda: CompanyMembershipFactory(user__notified_days_ago=31), id="company_admin_membership"),
            pytest.param(
                lambda: CompanyMembershipFactory(user__notified_days_ago=31, is_admin=False), id="company_membership"
            ),
            pytest.param(
                lambda: CompanyMembershipFactory(user__notified_days_ago=31, is_active=False),
                id="disabled_company_membership",
            ),
            pytest.param(
                lambda: InstitutionMembershipFactory(user__notified_days_ago=31), id="institution_admin_membership"
            ),
            pytest.param(
                lambda: InstitutionMembershipFactory(user__notified_days_ago=31, is_admin=False),
                id="institution_membership",
            ),
            pytest.param(
                lambda: InstitutionMembershipFactory(user__notified_days_ago=31, is_active=False),
                id="disabled_institution_membership",
            ),
        ],
    )
    def test_anonymized_professionals_annotations(self, factory, django_capture_on_commit_callbacks, snapshot):
        factory()

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
        settings.SUSPEND_ANONYMIZE_CANCELLED_APPROVALS = suspended
        call_command("anonymize_cancelled_approvals", wet_run=True)
        assert ("Anonymizing cancelled approvals is suspended, exiting command" in caplog.messages) == suspended

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
