# pylint: disable=too-many-lines
import datetime
import io
import json
from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail, management
from django.forms.models import model_to_dict
from django.template.defaultfilters import title
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, SuspensionFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordFactory
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.csv_export import generate_csv_export
from itou.job_applications.enums import RefusalReason, SenderKind
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationSentBySiaeFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.job_applications.notifications import NewQualifiedJobAppEmployersNotification
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipAndJobsFactory
from itou.siaes.models import Siae
from itou.users.factories import JobSeekerFactory, SiaeStaffFactory, UserFactory
from itou.users.models import User
from itou.utils.templatetags import format_filters


@override_settings(
    API_ESD={
        "BASE_URL": "https://base.domain",
        "AUTH_BASE_URL": "https://authentication-domain.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class JobApplicationModelTest(TestCase):
    def test_eligibility_diagnosis_by_siae_required(self, *args, **kwargs):
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=SiaeKind.GEIQ
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)
        self.assertFalse(job_application.eligibility_diagnosis_by_siae_required)

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=SiaeKind.EI
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)
        self.assertTrue(job_application.eligibility_diagnosis_by_siae_required)

    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_accepted_by(self, notification_mock):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        user = job_application.to_siae.members.first()
        job_application.accept(user=user)
        self.assertEqual(job_application.accepted_by, user)
        notification_mock.assert_called()

    def test_is_sent_by_authorized_prescriber(self, *args, **kwargs):

        job_application = JobApplicationSentByJobSeekerFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)
        job_application = JobApplicationSentByPrescriberFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentBySiaeFactory()
        self.assertFalse(job_application.is_sent_by_authorized_prescriber)

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        self.assertTrue(job_application.is_sent_by_authorized_prescriber)

    @patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
    def test_can_display_approval(self, *args, **kwargs):
        """
        A user can download an approval only when certain conditions
        are met:
        - the job_application.to_siae is subject to eligibility rules,
        - an approval exists (ie is not in the process of being delivered),
        - the job_application has been accepted.
        """
        job_application = JobApplicationWithApprovalFactory()
        self.assertTrue(job_application.can_display_approval)

        # SIAE not subject to eligibility rules.
        not_eligible_kinds = [kind for kind in SiaeKind if kind not in Siae.ELIGIBILITY_REQUIRED_KINDS]
        not_eligible_siae = SiaeFactory(kind=not_eligible_kinds[0])
        job_application = JobApplicationWithApprovalFactory(to_siae=not_eligible_siae)
        self.assertFalse(job_application.can_display_approval)

        # Application is not accepted.
        job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_OBSOLETE)
        self.assertFalse(job_application.can_display_approval)

        # Application accepted but without approval.
        job_application = JobApplicationFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        self.assertFalse(job_application.can_display_approval)

    def test_can_download_expired_approval(self, *args, **kwargs):
        # Approval has ended
        start = datetime.date.today() - relativedelta(years=2)
        ended_approval = ApprovalFactory(start_at=start)

        # `hiring_start_at` must be set in order to pass the `can_be_cancelled` condition
        # called by `can_display_approval`.
        job_application = JobApplicationWithApprovalFactory(approval=ended_approval, hiring_start_at=start)
        self.assertTrue(job_application.can_display_approval)

    def test_can_be_cancelled(self, *args, **kwargs):
        """
        A user can cancel a job application provided that it has no related
        employee record in SENT or PROCESSED state or that is does not come from
        AI stock.
        """
        today = datetime.date.today()
        job_application_ok = JobApplicationWithApprovalFactory(hiring_start_at=today)
        self.assertTrue(job_application_ok.can_be_cancelled)

        # Can be cancelled with a related employee record in NEW, READY, REJECTED status
        EmployeeRecordFactory(job_application=job_application_ok, status=Status.NEW)
        self.assertTrue(job_application_ok.can_be_cancelled)

        job_application_ok = JobApplicationWithApprovalFactory(hiring_start_at=today)
        EmployeeRecordFactory(job_application=job_application_ok, status=Status.READY)
        self.assertTrue(job_application_ok.can_be_cancelled)

        job_application_ok = JobApplicationWithApprovalFactory(hiring_start_at=today)
        EmployeeRecordFactory(job_application=job_application_ok, status=Status.REJECTED)
        self.assertTrue(job_application_ok.can_be_cancelled)

        # Can't be cancelled with a related employee record in PROCESSED or SENT status
        job_application_not_ok = JobApplicationWithApprovalFactory(hiring_start_at=today)
        EmployeeRecordFactory(job_application=job_application_not_ok, status=Status.SENT)
        self.assertFalse(job_application_not_ok.can_be_cancelled)

        job_application_not_ok = JobApplicationWithApprovalFactory(hiring_start_at=today)
        EmployeeRecordFactory(job_application=job_application_not_ok, status=Status.PROCESSED)
        self.assertFalse(job_application_not_ok.can_be_cancelled)

        # Comes from AI stock.
        # See users.management.commands.import_ai_employees
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        job_application = JobApplicationFactory.build(
            approval_manually_delivered_by=developer, created_at=settings.AI_EMPLOYEES_STOCK_IMPORT_DATE
        )
        self.assertFalse(job_application.can_be_cancelled)

    def test_can_be_archived(self, *args, **kwargs):
        """
        Only cancelled, refused and obsolete job_applications can be archived.
        """
        states_transition_not_possible = [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_ACCEPTED,
        ]
        states_transition_possible = [
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

        for state in states_transition_not_possible:
            job_application = JobApplicationFactory(state=state)
            self.assertFalse(job_application.can_be_archived)

        for state in states_transition_possible:
            job_application = JobApplicationFactory(state=state)
            self.assertTrue(job_application.can_be_archived)

    def test_is_from_ai_stock(self, *args, **kwargs):
        job_application_created_at = settings.AI_EMPLOYEES_STOCK_IMPORT_DATE
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)

        job_application = JobApplicationFactory.build()
        self.assertFalse(job_application.is_from_ai_stock)

        job_application = JobApplicationFactory.build(created_at=job_application_created_at)
        self.assertFalse(job_application.is_from_ai_stock)

        job_application = JobApplicationFactory.build(approval_manually_delivered_by=developer)
        self.assertFalse(job_application.is_from_ai_stock)

        job_application = JobApplicationFactory.build(
            created_at=job_application_created_at, approval_manually_delivered_by=developer
        )
        self.assertTrue(job_application.is_from_ai_stock)

    def test_candidate_has_employee_record(self, *args, **kwargs):

        # test job_application has no Approval
        job_application = JobApplicationWithoutApprovalFactory()
        self.assertFalse(job_application.candidate_has_employee_record)

        # test job_application has one Approval and no EmployeeRecord
        job_application = JobApplicationWithApprovalFactory()
        self.assertFalse(job_application.candidate_has_employee_record)

        # test job_application has one Approval and one EmployeeRecord
        job_application = JobApplicationWithApprovalFactory()
        EmployeeRecordFactory(job_application=job_application)
        self.assertTrue(job_application.candidate_has_employee_record)

        # test job_application has one Approval and no EmployeeRecord
        # but an EmployeeRecord already exists for the same approval.number
        # and the same Siae
        job_application1 = JobApplicationWithApprovalFactory()
        EmployeeRecordFactory(
            job_application=job_application1,
            asp_id=job_application1.to_siae.convention.asp_id,
            approval_number=job_application1.approval.number,
        )
        job_application2 = JobApplicationWithApprovalFactory(
            approval=job_application1.approval, to_siae=job_application1.to_siae
        )
        self.assertTrue(job_application1.candidate_has_employee_record)
        self.assertTrue(job_application2.candidate_has_employee_record)

        # test job_application has one Approval and no EmployeeRecord
        # but an EmployeeRecord already exists for the same approval.number
        # in an other Siae
        job_application1 = JobApplicationWithApprovalFactory()
        EmployeeRecordFactory(
            job_application=job_application1,
            asp_id=job_application1.to_siae.convention.asp_id,
            approval_number=job_application1.approval.number,
        )
        job_application2 = JobApplicationWithApprovalFactory(approval=job_application1.approval)
        self.assertTrue(job_application1.candidate_has_employee_record)
        self.assertFalse(job_application2.candidate_has_employee_record)

    def test_is_waiting_for_employee_record_creation(self, *args, **kwargs):

        today = datetime.date.today()
        job_application = JobApplicationWithApprovalFactory()
        to_siae = job_application.to_siae

        # test application with missing hiring_start_at (it’s an optional)
        job_application.hiring_start_at = None
        self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test application before EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
        day_in_the_past = settings.EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date() - relativedelta(months=2)
        job_application.hiring_start_at = day_in_the_past
        self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test application between EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE and today
        recent_day_in_the_past = (
            datetime.date.today() - relativedelta(settings.EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date(), today) / 2
        )
        job_application.hiring_start_at = recent_day_in_the_past
        self.assertTrue(job_application.is_waiting_for_employee_record_creation)

        # test application today
        job_application.hiring_start_at = today
        self.assertTrue(job_application.is_waiting_for_employee_record_creation)

        # test hiring without approval
        job_application_without_approval = JobApplicationWithoutApprovalFactory()
        self.assertFalse(job_application_without_approval.is_waiting_for_employee_record_creation)

        # test state not STATE_ACCEPTED
        states_transition_not_possible = [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

        for state in states_transition_not_possible:
            job_application.state = state
            self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test approval is invalid
        job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
        job_application.approval.start_at = timezone.now().date() - relativedelta(year=1)
        job_application.approval.end_at = timezone.now().date() - relativedelta(month=1)
        self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test SIAE cannot use Employee_Record
        job_application.hiring_start_at = today
        for siae_kind in [siae_kind for siae_kind in SiaeKind if siae_kind not in Siae.ASP_EMPLOYEE_RECORD_KINDS]:
            not_eligible_siae = SiaeFactory(kind=siae_kind)
            job_application.to_siae = not_eligible_siae
            self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test Employee_Record already exists
        job_application.to_siae = to_siae
        EmployeeRecordFactory(job_application=job_application)
        self.assertFalse(job_application.is_waiting_for_employee_record_creation)

        # test Employee_Record doesn't exists,
        # but an other EmployeeRecord exists for the same Approval and the same Siae
        job_application1 = JobApplicationWithApprovalFactory()
        EmployeeRecordFactory(
            job_application=job_application1,
            asp_id=job_application1.to_siae.convention.asp_id,
            approval_number=job_application1.approval.number,
        )
        job_application2 = JobApplicationWithApprovalFactory(
            approval=job_application1.approval, to_siae=job_application1.to_siae
        )
        self.assertFalse(job_application1.is_waiting_for_employee_record_creation)
        self.assertFalse(job_application2.is_waiting_for_employee_record_creation)


class JobApplicationQuerySetTest(TestCase):
    def test_created_in_past(self):
        now = timezone.now()
        hours_ago_10 = now - timezone.timedelta(hours=10)
        hours_ago_20 = now - timezone.timedelta(hours=20)
        hours_ago_30 = now - timezone.timedelta(hours=30)

        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_10)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_20)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_30)

        self.assertEqual(JobApplication.objects.created_in_past(hours=5).count(), 0)
        self.assertEqual(JobApplication.objects.created_in_past(hours=15).count(), 1)
        self.assertEqual(JobApplication.objects.created_in_past(hours=25).count(), 2)
        self.assertEqual(JobApplication.objects.created_in_past(hours=35).count(), 3)

    def test_get_unique_fk_objects(self):
        # Create 3 job applications for 2 candidates to check
        # that `get_unique_fk_objects` returns 2 candidates.
        JobApplicationSentByJobSeekerFactory()
        job_seeker = JobSeekerFactory()
        JobApplicationSentByJobSeekerFactory.create_batch(2, job_seeker=job_seeker)

        unique_job_seekers = JobApplication.objects.get_unique_fk_objects("job_seeker")

        self.assertEqual(JobApplication.objects.count(), 3)
        self.assertEqual(len(unique_job_seekers), 2)
        self.assertEqual(type(unique_job_seekers[0]), User)

    def test_with_has_suspended_approval(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_has_suspended_approval().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "has_suspended_approval"))
        self.assertFalse(qs.has_suspended_approval)

    def test_with_has_active_approval(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_has_suspended_approval().with_has_active_approval().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "has_active_approval"))
        self.assertFalse(qs.has_active_approval)

        job_app = JobApplicationWithApprovalFactory()
        qs = JobApplication.objects.with_has_suspended_approval().with_has_active_approval().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "has_active_approval"))
        self.assertTrue(qs.has_active_approval)

        job_app = JobApplicationWithApprovalFactory()
        SuspensionFactory(approval=job_app.approval)
        qs = JobApplication.objects.with_has_suspended_approval().with_has_active_approval().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "has_active_approval"))
        self.assertFalse(qs.has_active_approval)

    def test_with_last_change(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_last_change().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "last_change"))
        self.assertEqual(qs.last_change, job_app.created_at)

        job_app.process()
        qs = JobApplication.objects.with_last_change().get(pk=job_app.pk)
        last_change = job_app.logs.order_by("-timestamp").first()
        self.assertEqual(qs.last_change, last_change.timestamp)

    def test_with_is_pending_for_too_long(self):
        freshness_limit = timezone.now() - relativedelta(weeks=JobApplication.WEEKS_BEFORE_CONSIDERED_OLD)

        # Sent before the freshness limit.
        job_app = JobApplicationSentByJobSeekerFactory(created_at=freshness_limit - relativedelta(days=1))
        qs = JobApplication.objects.with_is_pending_for_too_long().get(pk=job_app.pk)
        self.assertTrue(hasattr(qs, "is_pending_for_too_long"))
        self.assertTrue(qs.is_pending_for_too_long)

        # Freshly sent.
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_is_pending_for_too_long().get(pk=job_app.pk)
        self.assertFalse(qs.is_pending_for_too_long)

        # Sent before the freshness limit but accepted.
        job_app = JobApplicationSentByJobSeekerFactory(
            created_at=freshness_limit - relativedelta(days=1), state=JobApplicationWorkflow.STATE_ACCEPTED
        )
        qs = JobApplication.objects.with_is_pending_for_too_long().get(pk=job_app.pk)
        self.assertFalse(qs.is_pending_for_too_long)

        # Freshly sent and freshly accepted. The Holy Grail!
        job_app = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        qs = JobApplication.objects.with_is_pending_for_too_long().get(pk=job_app.pk)
        self.assertFalse(qs.is_pending_for_too_long)

    def test_with_last_jobseeker_eligibility_diagnosis(self):
        job_app = JobApplicationWithApprovalFactory()
        diagnosis = EligibilityDiagnosisFactory(job_seeker=job_app.job_seeker)
        qs = JobApplication.objects.with_last_jobseeker_eligibility_diagnosis().get(pk=job_app.pk)
        self.assertEqual(qs.last_jobseeker_eligibility_diagnosis, diagnosis.pk)

    def test_with_last_eligibility_diagnosis_criterion(self):
        job_app = JobApplicationWithApprovalFactory()
        diagnosis = EligibilityDiagnosisFactory(job_seeker=job_app.job_seeker)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteria.Level.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        qs = (
            JobApplication.objects.with_last_jobseeker_eligibility_diagnosis()
            .with_last_eligibility_diagnosis_criterion(level1_criterion.pk)
            .with_last_eligibility_diagnosis_criterion(level2_criterion.pk)
            .with_last_eligibility_diagnosis_criterion(level1_other_criterion.pk)
            .get(pk=job_app.pk)
        )
        self.assertTrue(getattr(qs, f"last_eligibility_diagnosis_criterion_{level1_criterion.pk}"))
        self.assertTrue(getattr(qs, f"last_eligibility_diagnosis_criterion_{level2_criterion.pk}"))
        self.assertFalse(getattr(qs, f"last_eligibility_diagnosis_criterion_{level1_other_criterion.pk}"))

    def test_with_list_related_data(self):
        job_app = JobApplicationWithApprovalFactory()
        diagnosis = EligibilityDiagnosisFactory(job_seeker=job_app.job_seeker)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteria.Level.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        criteria = [level1_criterion.pk, level2_criterion.pk, level1_other_criterion.pk]
        qs = JobApplication.objects.with_list_related_data(criteria).get(pk=job_app.pk)

        self.assertTrue(hasattr(qs, "approval"))
        self.assertTrue(hasattr(qs, "job_seeker"))
        self.assertTrue(hasattr(qs, "sender"))
        self.assertTrue(hasattr(qs, "sender_siae"))
        self.assertTrue(hasattr(qs, "sender_prescriber_organization"))
        self.assertTrue(hasattr(qs, "to_siae"))
        self.assertTrue(hasattr(qs, "selected_jobs"))
        self.assertTrue(hasattr(qs, "has_suspended_approval"))
        self.assertTrue(hasattr(qs, "is_pending_for_too_long"))
        self.assertTrue(hasattr(qs, "has_active_approval"))
        self.assertTrue(hasattr(qs, "last_jobseeker_eligibility_diagnosis"))
        self.assertTrue(hasattr(qs, f"last_eligibility_diagnosis_criterion_{level1_criterion.pk}"))
        self.assertTrue(hasattr(qs, f"last_eligibility_diagnosis_criterion_{level2_criterion.pk}"))
        self.assertTrue(hasattr(qs, f"last_eligibility_diagnosis_criterion_{level1_other_criterion.pk}"))

    def test_eligible_as_employee_record(self):
        # Results must be a list of job applications:
        # Accepted
        job_app = JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW)
        self.assertNotIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # With an approval
        job_app = JobApplicationWithoutApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        self.assertNotIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # Approval `create_employee_record` is False.
        job_app = JobApplicationWithApprovalNotCancellableFactory(create_employee_record=False)
        self.assertNotIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # Must be accepted and only after CANCELLATION_DAYS_AFTER_HIRING_STARTED
        job_app = JobApplicationFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        self.assertNotIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # Approval start date is also checked (must be older then CANCELLATION_DAY_AFTER_HIRING STARTED).
        job_app = JobApplicationWithApprovalNotCancellableFactory()
        self.assertIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # After employee record creation
        job_app = JobApplicationWithCompleteJobSeekerProfileFactory()
        employee_record = EmployeeRecordFactory(
            job_application=job_app,
            asp_id=job_app.to_siae.convention.asp_id,
            approval_number=job_app.approval.number,
            status=Status.PROCESSED,
        )
        self.assertNotIn(job_app, JobApplication.objects.eligible_as_employee_record(job_app.to_siae))

        # After employee record is disabled
        employee_record.update_as_disabled()
        self.assertEqual(employee_record.status, Status.DISABLED)


class JobApplicationNotificationsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            selected_jobs=Appellation.objects.all(),
        )
        email = NewQualifiedJobAppEmployersNotification(job_application=job_application).email
        # To.
        self.assertIn(job_application.to_siae.members.first().email, email.to)
        self.assertEqual(len(email.to), 1)

        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.get_full_name(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.to_siae.city, email.body)
        self.assertIn(str(job_application.to_siae.pk), email.body)
        self.assertIn(job_application.resume_link, email.body)

    def test_new_for_prescriber(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            selected_jobs=Appellation.objects.all()
        )
        email = job_application.email_new_for_prescriber
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(job_application.sender_kind, SenderKind.PRESCRIBER)

        # Subject
        self.assertIn(job_application.job_seeker.get_full_name(), email.subject)

        # Body.
        self.assertIn(job_application.job_seeker.first_name.title(), email.body)
        self.assertIn(job_application.job_seeker.last_name.title(), email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.get_full_name().title(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.to_siae.kind, email.body)
        self.assertIn(job_application.to_siae.city, email.body)

        # Assert the Job Seeker does not have access to confidential information.
        email = job_application.email_new_for_job_seeker()
        self.assertIn(job_application.sender.get_full_name().title(), email.body)
        self.assertIn(job_application.sender_prescriber_organization.display_name, email.body)
        self.assertNotIn(job_application.sender.email, email.body)
        self.assertNotIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.resume_link, email.body)

    def test_new_for_job_seeker(self, *args, **kwargs):
        job_application = JobApplicationSentByJobSeekerFactory(selected_jobs=Appellation.objects.all())
        email = job_application.email_new_for_job_seeker()
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(job_application.sender_kind, SenderKind.JOB_SEEKER)

        # Subject
        self.assertIn(job_application.to_siae.display_name, email.subject)

        # Body.
        self.assertIn(job_application.job_seeker.first_name.title(), email.body)
        self.assertIn(job_application.job_seeker.last_name.title(), email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.job_seeker.phone), email.body)
        self.assertIn(job_application.message, email.body)
        for job in job_application.selected_jobs.all():
            self.assertIn(job.display_name, email.body)
        self.assertIn(job_application.sender.first_name.title(), email.body)
        self.assertIn(job_application.sender.last_name.title(), email.body)
        self.assertIn(job_application.sender.email, email.body)
        self.assertIn(format_filters.format_phone(job_application.sender.phone), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(reverse("login:job_seeker"), email.body)
        self.assertIn(reverse("account_reset_password"), email.body)
        self.assertIn(job_application.resume_link, email.body)

    def test_accept_for_job_seeker(self, *args, **kwargs):
        job_application = JobApplicationSentByJobSeekerFactory()
        email = job_application.email_accept_for_job_seeker
        # To.
        self.assertEqual(job_application.job_seeker.email, job_application.sender.email)
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 0)
        # Subject.
        self.assertIn("Candidature acceptée", email.subject)
        # Body.
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)

    def test_accept_for_proxy(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        email = job_application.email_accept_for_proxy
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 0)
        # Subject.
        self.assertIn("Candidature acceptée et votre avis sur les emplois de l'inclusion", email.subject)
        # Body.
        self.assertIn(title(job_application.job_seeker.get_full_name()), email.body)
        self.assertIn(title(job_application.sender.get_full_name()), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)
        self.assertIn("Date de début du contrat", email.body)
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn("Date de fin du contrat", email.body)
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.sender_prescriber_organization.accept_survey_url, email.body)

    def test_accept_for_proxy_without_hiring_end_at(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(hiring_end_at=None)
        email = job_application.email_accept_for_proxy
        self.assertIn("Date de fin du contrat : Non renseigné", email.body)

    def test_accept_trigger_manual_approval(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED, hiring_start_at=datetime.date.today()
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        # To.
        self.assertIn(settings.ITOU_EMAIL_CONTACT, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)
        self.assertIn(job_application.job_seeker.email, email.body)
        self.assertIn(job_application.job_seeker.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.to_siae.siret, email.body)
        self.assertIn(job_application.to_siae.kind, email.body)
        self.assertIn(job_application.to_siae.get_kind_display(), email.body)
        self.assertIn(job_application.to_siae.get_department_display(), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(accepted_by.get_full_name(), email.body)
        self.assertIn(accepted_by.email, email.body)
        self.assertIn(reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk]), email.body)

    def test_accept_trigger_manual_approval_without_hiring_end_at(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED, hiring_start_at=datetime.date.today(), hiring_end_at=None
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        self.assertIn("Date de fin du contrat : Non renseigné", email.body)

    def test_refuse(self, *args, **kwargs):

        # When sent by authorized prescriber.
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.email_refuse_for_proxy
        # To.
        self.assertIn(job_application.sender.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.sender.first_name.title(), email.body)
        self.assertIn(job_application.sender.last_name.title(), email.body)
        self.assertIn(job_application.job_seeker.first_name.title(), email.body)
        self.assertIn(job_application.job_seeker.last_name.title(), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)
        self.assertIn(job_application.answer_to_prescriber, email.body)

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.email_refuse_for_job_seeker
        # To.
        self.assertEqual(job_application.job_seeker.email, job_application.sender.email)
        self.assertIn(job_application.job_seeker.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.answer, email.body)
        self.assertNotIn(job_application.answer_to_prescriber, email.body)

    def test_email_deliver_approval(self, *args, **kwargs):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_ACCEPTED, approval=approval
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_deliver_approval(accepted_by)
        # To.
        self.assertIn(accepted_by.email, email.to)
        self.assertEqual(len(email.to), 1)
        # Body.
        self.assertIn(approval.user.get_full_name(), email.subject)
        self.assertIn(approval.number_with_spaces, email.body)
        self.assertIn(approval.start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(approval.end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(approval.user.last_name, email.body)
        self.assertIn(approval.user.first_name, email.body)
        self.assertIn(approval.user.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(job_application.to_siae.display_name, email.body)
        self.assertIn(job_application.to_siae.get_kind_display(), email.body)
        self.assertIn(job_application.to_siae.address_line_1, email.body)
        self.assertIn(job_application.to_siae.address_line_2, email.body)
        self.assertIn(job_application.to_siae.post_code, email.body)
        self.assertIn(job_application.to_siae.city, email.body)
        self.assertIn(settings.ITOU_ASSISTANCE_URL, email.body)
        self.assertIn(job_application.to_siae.accept_survey_url, email.body)

    def test_email_deliver_approval_without_hiring_end_at(self, *args, **kwargs):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_ACCEPTED, approval=approval, hiring_end_at=None
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_deliver_approval(accepted_by)
        self.assertIn("Se terminant le : Non renseigné", email.body)

    def test_email_deliver_approval_when_subject_to_eligibility_rules(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory(to_siae__subject_to_eligibility=True)

        email = job_application.email_deliver_approval(job_application.to_siae.members.first())

        self.assertEqual(
            f"PASS IAE pour {job_application.job_seeker.get_full_name()} et avis sur les emplois de l'inclusion",
            email.subject,
        )
        self.assertIn("PASS IAE", email.body)

    def test_email_deliver_approval_when_not_subject_to_eligibility_rules(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory(to_siae__not_subject_to_eligibility=True)

        email = job_application.email_deliver_approval(job_application.to_siae.members.first())

        self.assertEqual("Confirmation de l'embauche", email.subject)
        self.assertNotIn("PASS IAE", email.body)
        self.assertIn(settings.ITOU_ASSISTANCE_URL, email.body)

    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_manually_deliver_approval(self, *args, **kwargs):
        staff_member = UserFactory(is_staff=True)
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval=approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_deliver_approval(delivered_by=staff_member)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertIsNotNone(job_application.approval_number_sent_at)
        self.assertEqual(job_application.approval_manually_delivered_by, staff_member)
        self.assertIsNone(job_application.approval_manually_refused_at)
        self.assertIsNone(job_application.approval_manually_refused_by)
        self.assertEqual(len(mail.outbox), 1)

    def test_manually_refuse_approval(self, *args, **kwargs):
        staff_member = UserFactory(is_staff=True)
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_refuse_approval(refused_by=staff_member)
        self.assertEqual(job_application.approval_manually_refused_by, staff_member)
        self.assertIsNotNone(job_application.approval_manually_refused_at)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertIsNone(job_application.approval_manually_delivered_by)
        self.assertIsNone(job_application.approval_number_sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_cancel(self, *args, **kwargs):
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED
        )

        cancellation_user = job_application.to_siae.active_members.first()
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        self.assertIn(cancellation_user.email, email.to)
        self.assertIn(job_application.sender.email, email.bcc)
        self.assertEqual(len(email.to), 1)
        self.assertEqual(len(email.bcc), 1)
        # Body.
        self.assertIn("annulée", email.body)
        self.assertIn(job_application.sender.first_name, email.body)
        self.assertIn(job_application.sender.last_name, email.body)
        self.assertIn(job_application.job_seeker.first_name, email.body)
        self.assertIn(job_application.job_seeker.last_name, email.body)

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        self.assertFalse(email.bcc)


class NewQualifiedJobAppEmployersNotificationTest(TestCase):
    def test_one_selected_job(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_descriptions = siae.job_description_through.all()

        selected_job = job_descriptions[0]
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])

        membership = siae.siaemembership_set.first()
        self.assertFalse(membership.notifications)
        NewQualifiedJobAppEmployersNotification.subscribe(recipient=membership, subscribed_pks=[selected_job.pk])
        self.assertTrue(
            NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=membership, subscribed_pk=selected_job.pk)
        )

        # Receiver is now subscribed to one kind of notification
        self.assertEqual(
            # pylint: disable=protected-access
            len(NewQualifiedJobAppEmployersNotification._get_recipient_subscribed_pks(recipient=membership)),
            1,
        )

        # A job application is sent concerning another job_description.
        # He should then be subscribed to two different notifications.
        selected_job = job_descriptions[1]
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])

        NewQualifiedJobAppEmployersNotification.subscribe(recipient=membership, subscribed_pks=[selected_job.pk])
        self.assertTrue(
            NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=membership, subscribed_pk=selected_job.pk)
        )

        self.assertEqual(
            # pylint: disable=protected-access
            len(NewQualifiedJobAppEmployersNotification._get_recipient_subscribed_pks(recipient=membership)),
            2,
        )
        self.assertEqual(len(membership.notifications), 1)

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), 1)

    def test_multiple_selected_jobs_multiple_recipients(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_descriptions = siae.job_description_through.all()[:2]

        membership = siae.siaemembership_set.first()
        NewQualifiedJobAppEmployersNotification.subscribe(
            recipient=membership, subscribed_pks=[job_descriptions[0].pk]
        )

        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)
        membership = siae.siaemembership_set.get(user=user)
        NewQualifiedJobAppEmployersNotification.subscribe(
            recipient=membership, subscribed_pks=[job_descriptions[1].pk]
        )

        # Two selected jobs. Each user subscribed to one of them. We should have two recipients.
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=job_descriptions)
        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)

        self.assertEqual(len(notification.recipients_emails), 2)

    def test_default_subscription(self):
        """
        Unset recipients should receive new job application notifications.
        """
        siae = SiaeWithMembershipAndJobsFactory()
        user = SiaeStaffFactory(siae=siae)
        siae.members.add(user)

        selected_job = siae.job_description_through.first()
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)

        recipients = notification.recipients_emails
        self.assertEqual(len(recipients), siae.members.count())

    def test_unsubscribe(self):
        siae = SiaeWithMembershipAndJobsFactory()
        selected_job = siae.job_description_through.first()
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])
        self.assertEqual(siae.members.count(), 1)

        recipient = siae.siaemembership_set.first()

        NewQualifiedJobAppEmployersNotification.subscribe(recipient=recipient, subscribed_pks=[selected_job.pk])
        self.assertTrue(
            NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=selected_job.pk)
        )

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        self.assertEqual(len(notification.recipients_emails), 1)

        NewQualifiedJobAppEmployersNotification.unsubscribe(recipient=recipient, subscribed_pks=[selected_job.pk])
        self.assertFalse(
            NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=selected_job.pk)
        )

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        self.assertEqual(len(notification.recipients_emails), 0)


@override_settings(
    API_ESD={
        "BASE_URL": "https://base.domain",
        "AUTH_BASE_URL": "https://authentication-domain.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
@patch("itou.job_applications.models.huey_notify_pole_emploi")
class JobApplicationWorkflowTest(TestCase):
    def setUp(self):
        self.sent_pass_email_subject = "PASS IAE pour"
        self.accept_email_subject_proxy = "Candidature acceptée et votre avis sur les emplois de l'inclusion"
        self.accept_email_subject_job_seeker = "Candidature acceptée"

    def test_accept_job_application_sent_by_job_seeker_and_make_others_obsolete(self, notify_mock):
        """
        When a job seeker's application is accepted, the others are marked obsolete.
        """
        job_seeker = JobSeekerFactory()
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_seeker.pole_emploi_id, "")

        kwargs = {"job_seeker": job_seeker, "sender": job_seeker, "sender_kind": SenderKind.JOB_SEEKER}
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)

        self.assertEqual(job_seeker.job_applications.count(), 4)
        self.assertEqual(job_seeker.job_applications.pending().count(), 4)

        job_application = job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_PROCESSING).first()
        job_application.accept(user=job_application.to_siae.members.first())

        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count(), 1)
        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).count(), 3)

        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[1].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_obsolete(self, notify_mock):
        """
        An obsolete job application can be accepted.
        """
        job_seeker = JobSeekerFactory()

        kwargs = {"job_seeker": job_seeker, "sender": job_seeker, "sender_kind": SenderKind.JOB_SEEKER}
        for state in [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_OBSOLETE,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]:
            JobApplicationFactory(state=state, **kwargs)

        self.assertEqual(job_seeker.job_applications.count(), 6)

        job_application = job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).first()
        job_application.accept(user=job_application.to_siae.members.first())

        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count(), 2)
        self.assertEqual(job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).count(), 4)

        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[1].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval(self, notify_mock):
        """
        When a Pôle emploi approval already exists, it is reused.
        """
        job_seeker = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval.number, pe_approval.number)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[1].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval_with_nir(
        self, notify_mock
    ):
        job_seeker = JobSeekerFactory(pole_emploi_id="", birthdate=None)
        pe_approval = PoleEmploiApprovalFactory(nir=job_seeker.nir)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval.number, pe_approval.number)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[1].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_with_forgotten_pole_emploi_id(self, notify_mock):
        """
        When a Pôle emploi ID is forgotten, a manual approval delivery is triggered.
        """
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNone(job_application.approval)
        self.assertEqual(job_application.approval_delivery_mode, JobApplication.APPROVAL_DELIVERY_MODE_MANUAL)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the team.
        self.assertIn("PASS IAE requis sur Itou", mail.outbox[1].subject)
        # no approval, so no notification sent to pole emploi
        notify_mock.assert_not_called()

    def test_accept_job_application_sent_by_job_seeker_with_a_nir_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            pole_emploi_id="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval_delivery_mode, JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour ", mail.outbox[1].subject)
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_with_a_pole_emploi_id_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            nir="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval_delivery_mode, JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour ", mail.outbox[1].subject)
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_unregistered_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_NOT_REGISTERED
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertEqual(job_application.approval_delivery_mode, JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Candidature acceptée", mail.outbox[0].subject)
        self.assertIn("PASS IAE pour ", mail.outbox[1].subject)
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_prescriber(self, notify_mock):
        """
        Accept a job application sent by an "orienteur".
        """
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 3)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the proxy.
        self.assertIn(self.accept_email_subject_proxy, mail.outbox[1].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[2].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_authorized_prescriber(self, notify_mock):
        """
        Accept a job application sent by an authorized prescriber.
        """
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertTrue(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent email.
        self.assertEqual(len(mail.outbox), 3)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the proxy.
        self.assertIn(self.accept_email_subject_proxy, mail.outbox[1].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[2].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_authorized_prescriber_with_approval_in_waiting_period(self, notify_mock):
        """
        An authorized prescriber can bypass the waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertTrue(approval.is_in_waiting_period)
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 3)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the proxy.
        self.assertIn(self.accept_email_subject_proxy, mail.outbox[1].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[2].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_prescriber_with_approval_in_waiting_period(self, notify_mock):
        """
        An "orienteur" cannot bypass the waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertTrue(approval.is_in_waiting_period)
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.accept(user=job_application.to_siae.members.first())
            notify_mock.assert_not_called()

    def test_accept_job_application_sent_by_job_seeker_in_waiting_period_valid_diagnosis(self, notify_mock):
        """
        A job seeker with a valid diagnosis can start an IAE path
        even if he's in a waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertTrue(approval.is_in_waiting_period)

        diagnosis = EligibilityDiagnosisFactory(job_seeker=user)
        self.assertTrue(diagnosis.is_valid)

        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertIsNotNone(job_application.approval)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC)
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the employer.
        self.assertIn(self.sent_pass_email_subject, mail.outbox[1].subject)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_by_siae_with_no_approval(self, notify_mock):
        """
        A SIAE can hire somebody without getting approval if they don't want one
        Basically the same as the 'accept' part, except we don't create an approval
        and we don't notify
        """
        job_application = JobApplicationWithoutApprovalFactory(state=JobApplicationWorkflow.STATE_PROCESSING)
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_application.job_seeker.pole_emploi_id, "")
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertTrue(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNone(job_application.approval)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, "")
        # Check sent email (no notification of approval).
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the proxy.
        self.assertIn(self.accept_email_subject_proxy, mail.outbox[1].subject)
        # No approval, so no notification is sent to Pole Emploi
        notify_mock.assert_not_called()

    def test_accept_job_application_by_siae_not_subject_to_eligibility_rules(self, notify_mock):
        """
        No approval should be delivered for an employer not subject to eligibility rules.
        """
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=SiaeKind.GEIQ
        )
        job_application.accept(user=job_application.to_siae.members.first())
        self.assertFalse(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertIsNone(job_application.approval)
        self.assertFalse(job_application.approval_number_sent_by_email)
        self.assertEqual(job_application.approval_delivery_mode, "")
        # Check sent emails.
        self.assertEqual(len(mail.outbox), 2)
        # Email sent to the job seeker.
        self.assertIn(self.accept_email_subject_job_seeker, mail.outbox[0].subject)
        # Email sent to the proxy.
        self.assertIn(self.accept_email_subject_proxy, mail.outbox[1].subject)
        # No approval, so no notification is sent to Pole Emploi
        notify_mock.assert_not_called()

    def test_accept_has_link_to_eligibility_diagnosis(self, notify_mock):
        """
        Given a job application for an SIAE subject to eligibility rules,
        when accepting it, then the eligibility diagnosis is linked to it.
        """
        job_application = JobApplicationSentBySiaeFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae__kind=SiaeKind.EI,
        )

        to_siae = job_application.to_siae
        to_siae_staff_member = to_siae.members.first()
        job_seeker = job_application.job_seeker

        eligibility_diagnosis = EligibilityDiagnosisMadeBySiaeFactory(
            job_seeker=job_seeker, author=to_siae_staff_member, author_siae=to_siae
        )

        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        self.assertNotEqual(job_seeker.pole_emploi_id, "")

        job_application.accept(user=to_siae_staff_member)
        self.assertTrue(job_application.to_siae.is_subject_to_eligibility_rules)
        self.assertEqual(job_application.eligibility_diagnosis, eligibility_diagnosis)
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_refuse(self, notify_mock):
        user = JobSeekerFactory()
        kwargs = {"job_seeker": user, "sender": user, "sender_kind": SenderKind.JOB_SEEKER}

        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)

        self.assertEqual(user.job_applications.count(), 2)
        self.assertEqual(user.job_applications.pending().count(), 2)

        for job_application in user.job_applications.all():
            job_application.refuse()
            # Check sent email.
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("Candidature déclinée", mail.outbox[0].subject)
            mail.outbox = []
            # Approval refused -> Pole Emploi is not notified, because they don’t care
            notify_mock.assert_not_called()

    def test_cancel_delete_linked_approval(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()
        self.assertEqual(job_application.job_seeker.approvals.count(), 1)
        self.assertEqual(JobApplication.objects.filter(approval=job_application.approval).count(), 1)

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_CANCELLED)

        job_application.refresh_from_db()
        self.assertFalse(job_application.approval)

    def test_cancel_do_not_delete_linked_approval(self, *args, **kwargs):

        # The approval is linked to two accepted job applications
        job_application = JobApplicationWithApprovalFactory()
        approval = job_application.approval
        JobApplicationWithApprovalFactory(approval=approval, job_seeker=job_application.job_seeker)

        self.assertEqual(job_application.job_seeker.approvals.count(), 1)
        self.assertEqual(JobApplication.objects.filter(approval=approval).count(), 2)

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        self.assertEqual(job_application.state, JobApplicationWorkflow.STATE_CANCELLED)

        job_application.refresh_from_db()
        self.assertTrue(job_application.approval)

    def test_cancellation_not_allowed(self, *args, **kwargs):
        today = datetime.date.today()

        # Linked employee record with blocking status
        job_application = JobApplicationWithApprovalFactory(hiring_start_at=(today - relativedelta(days=365)))
        cancellation_user = job_application.to_siae.active_members.first()
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        # xworkflows.base.AbortTransition
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)

        # Wrong state
        job_application = JobApplicationWithApprovalFactory(
            hiring_start_at=today, state=JobApplicationWorkflow.STATE_NEW
        )
        cancellation_user = job_application.to_siae.active_members.first()
        with self.assertRaises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)


class JobApplicationCsvExportTest(TestCase):
    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_csv_export_contains_the_necessary_info(self, *args, **kwargs):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            selected_jobs=Appellation.objects.all(),
        )
        job_application.accept(user=job_application.to_siae.members.first())

        # The accept transition above will create a valid PASS IAE for the job seeker.
        self.assertTrue(job_seeker.approvals.last().is_valid)

        csv_output = io.StringIO()
        generate_csv_export(JobApplication.objects, csv_output)
        self.maxDiff = None
        self.assertIn(job_seeker.first_name, csv_output.getvalue())
        self.assertIn(job_seeker.last_name, csv_output.getvalue())
        self.assertIn(job_seeker.first_name, csv_output.getvalue())
        self.assertIn(job_seeker.last_name, csv_output.getvalue())
        self.assertIn(job_seeker.email, csv_output.getvalue())
        self.assertIn(job_seeker.phone, csv_output.getvalue())
        self.assertIn(job_seeker.birthdate.strftime("%d/%m/%Y"), csv_output.getvalue())
        self.assertIn(job_seeker.city, csv_output.getvalue())
        self.assertIn(job_seeker.post_code, csv_output.getvalue())
        self.assertIn(job_application.to_siae.display_name, csv_output.getvalue())
        self.assertIn(job_application.to_siae.kind, csv_output.getvalue())
        self.assertIn(job_application.selected_jobs.first().display_name, csv_output.getvalue())
        self.assertIn("Candidature spontanée", csv_output.getvalue())
        self.assertIn(job_application.created_at.strftime("%d/%m/%Y"), csv_output.getvalue())
        self.assertIn(job_application.hiring_start_at.strftime("%d/%m/%Y"), csv_output.getvalue())
        self.assertIn(job_application.hiring_end_at.strftime("%d/%m/%Y"), csv_output.getvalue())
        self.assertIn("oui", csv_output.getvalue())  # Eligibility status.
        self.assertIn(job_application.approval.number, csv_output.getvalue())
        self.assertIn(job_application.approval.start_at.strftime("%d/%m/%Y"), csv_output.getvalue())
        self.assertIn(job_application.approval.end_at.strftime("%d/%m/%Y"), csv_output.getvalue())

    def test_refused_job_application_has_reason_in_csv_export(self, *args, **kwargs):
        user = JobSeekerFactory()
        kwargs = {
            "job_seeker": user,
            "sender": user,
            "sender_kind": SenderKind.JOB_SEEKER,
            "refusal_reason": RefusalReason.DID_NOT_COME,
        }

        job_application = JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        job_application.refuse()

        csv_output = io.StringIO()
        generate_csv_export(JobApplication.objects, csv_output)

        self.assertIn("Candidature déclinée", csv_output.getvalue())
        self.assertIn("Candidat non joignable", csv_output.getvalue())


class JobApplicationAdminFormTest(TestCase):
    def test_job_application_admin_form_validation(self):

        form_fields_list = [
            "job_seeker",
            "eligibility_diagnosis",
            "create_employee_record",
            "resume_link",
            "sender",
            "sender_kind",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae",
            "state",
            "selected_jobs",
            "message",
            "answer",
            "answer_to_prescriber",
            "refusal_reason",
            "hiring_start_at",
            "hiring_end_at",
            "hiring_without_approval",
            "created_from_pe_approval",
            "approval",
            "approval_delivery_mode",
            "approval_number_sent_by_email",
            "approval_number_sent_at",
            "approval_manually_delivered_by",
            "approval_manually_refused_by",
            "approval_manually_refused_at",
            "hidden_for_siae",
            "transferred_at",
            "transferred_by",
            "transferred_from",
            "created_at",
            "updated_at",
        ]
        form = JobApplicationAdminForm()
        self.assertEqual(list(form.fields.keys()), form_fields_list)

        # mandatory fields : job_seeker, to_siae
        form_errors = {
            "job_seeker": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "to_siae": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "state": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "created_at": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "__all__": [{"message": "Emetteur prescripteur manquant.", "code": ""}],
        }

        data = {"sender_kind": SenderKind.PRESCRIBER}
        form = JobApplicationAdminForm(data)
        self.assertEqual(form.errors.as_json(), json.dumps(form_errors))

    def test_applications_sent_by_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        sender = job_application.sender
        sender_kind = job_application.sender_kind
        sender_siae = job_application.sender_siae

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur candidat manquant."], form.errors["__all__"])
        job_application.sender = sender

        job_application.sender_kind = SenderKind.PRESCRIBER
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur du mauvais type."], form.errors["__all__"])
        job_application.sender_kind = sender_kind

        job_application.sender_siae = JobApplicationSentBySiaeFactory().sender_siae
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["SIAE émettrice inattendue."], form.errors["__all__"])
        job_application.sender_siae = sender_siae

        job_application.sender_prescriber_organization = (
            JobApplicationSentByPrescriberOrganizationFactory().sender_prescriber_organization
        )
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Organisation du prescripteur émettrice inattendue."], form.errors["__all__"])
        job_application.sender_prescriber_organization = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertTrue(form.is_valid())

    def test_applications_sent_by_siae(self):
        job_application = JobApplicationSentBySiaeFactory()
        sender_siae = job_application.sender_siae
        sender = job_application.sender

        job_application.sender_siae = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["SIAE émettrice manquante."], form.errors["__all__"])
        job_application.sender_siae = sender_siae

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur du mauvais type."], form.errors["__all__"])

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur SIAE manquant."], form.errors["__all__"])
        job_application.sender = sender

        job_application.sender_prescriber_organization = (
            JobApplicationSentByPrescriberOrganizationFactory().sender_prescriber_organization
        )
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Organisation du prescripteur émettrice inattendue."], form.errors["__all__"])
        job_application.sender_prescriber_organization = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertTrue(form.is_valid())

    def test_applications_sent_by_prescriber_with_organization(self):
        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur du mauvais type."], form.errors["__all__"])

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur prescripteur manquant."], form.errors["__all__"])
        job_application.sender = sender

        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Organisation du prescripteur émettrice manquante."], form.errors["__all__"])
        job_application.sender_prescriber_organization = sender_prescriber_organization

        job_application.sender_siae = JobApplicationSentBySiaeFactory().sender_siae
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["SIAE émettrice inattendue."], form.errors["__all__"])
        job_application.sender_siae = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertTrue(form.is_valid())

    def test_applications_sent_by_prescriber_without_organization(self):
        job_application = JobApplicationSentByPrescriberFactory()
        sender = job_application.sender

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur du mauvais type."], form.errors["__all__"])

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertFalse(form.is_valid())
        self.assertEqual(["Emetteur prescripteur manquant."], form.errors["__all__"])
        job_application.sender = sender

        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertTrue(form.is_valid())

        # explicit redundant test
        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        self.assertTrue(form.is_valid())


class JobApplicationsEnumsTest(TestCase):
    def test_refusal_reason(self):
        """Some reasons are kept for history but not displayed to end users."""
        hidden_choices = RefusalReason.hidden()
        for choice in hidden_choices:
            reasons = [choice[0] for choice in RefusalReason.displayed_choices()]
            self.assertTrue(len(reasons) > 0)
            with self.subTest(choice):
                self.assertNotIn(choice.value, reasons)


class DisplayMissingEligibilityDiagnosesCommandTest(TestCase):
    def test_nominal(self):
        stdout = io.StringIO()
        user = UserFactory(email="batman@batcave.org")
        ja = JobApplicationWithApprovalFactory(
            eligibility_diagnosis=None, state="accepted", approval__number="999991234567", approval__created_by=user
        )
        management.call_command("display_missing_eligibility_diagnoses", stdout=stdout)
        self.assertEqual(
            stdout.getvalue().split("\n"),
            [
                "number,created_at,started_at,end_at,created_by,job_seeker",
                f"{ja.approval.number},{ja.approval.created_at.isoformat()},{ja.approval.start_at},"
                f"{ja.approval.end_at},{ja.approval.created_by},{ja.approval.user}",
                "",
            ],
        )
