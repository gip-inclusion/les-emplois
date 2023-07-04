# pylint: disable=too-many-lines
import datetime
import io
import json
from unittest.mock import patch

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail, management
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.forms.models import model_to_dict
from django.template.defaultfilters import title
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, ProlongationFactory, SuspensionFactory
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.factories import BareEmployeeRecordFactory, EmployeeRecordFactory
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.enums import Origin, QualificationLevel, QualificationType, RefusalReason, SenderKind
from itou.job_applications.export import JOB_APPLICATION_CSV_HEADERS, stream_xlsx_export
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationSentBySiaeFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.job_applications.notifications import NewQualifiedJobAppEmployersNotification
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.enums import ContractType, SiaeKind
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipAndJobsFactory
from itou.users.factories import ItouStaffFactory, JobSeekerFactory, PrescriberFactory, SiaeStaffFactory
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.templatetags import format_filters
from tests.utils.test import TestCase, get_rows_from_streaming_response


@override_settings(
    API_ESD={
        "BASE_URL": "https://base.domain",
        "AUTH_BASE_URL": "https://authentication-domain.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class JobApplicationModelTest(TestCase):
    def test_eligibility_diagnosis_by_siae_required(self):
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae__kind=SiaeKind.GEIQ,
            eligibility_diagnosis=None,
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        assert not has_considered_valid_diagnoses
        assert not job_application.eligibility_diagnosis_by_siae_required

        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae__kind=SiaeKind.EI,
            eligibility_diagnosis=None,
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        assert not has_considered_valid_diagnoses
        assert job_application.eligibility_diagnosis_by_siae_required

    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_accepted_by(self, notification_mock):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        user = job_application.to_siae.members.first()
        job_application.accept(user=user)
        assert job_application.accepted_by == user
        notification_mock.assert_called()

    def test_is_sent_by_authorized_prescriber(self):

        job_application = JobApplicationSentByJobSeekerFactory()
        assert not job_application.is_sent_by_authorized_prescriber
        job_application = JobApplicationSentByPrescriberFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationSentBySiaeFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        assert job_application.is_sent_by_authorized_prescriber

    def test_can_be_archived(self):
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
            assert not job_application.can_be_archived

        for state in states_transition_possible:
            job_application = JobApplicationFactory(state=state)
            assert job_application.can_be_archived

    def test_candidate_has_employee_record(self):

        # test job_application has no Approval
        job_application = JobApplicationWithoutApprovalFactory()
        assert not job_application.candidate_has_employee_record

        # test job_application has one Approval and no EmployeeRecord
        job_application = JobApplicationFactory(with_approval=True)
        assert not job_application.candidate_has_employee_record

        # test job_application has one Approval and one EmployeeRecord
        job_application = JobApplicationFactory(
            with_approval=True,
        )
        EmployeeRecordFactory(job_application=job_application)
        assert job_application.candidate_has_employee_record

        # test job_application has one Approval and no EmployeeRecord
        # but an EmployeeRecord already exists for the same approval.number
        # and the same Siae
        job_application1 = JobApplicationFactory(with_approval=True)
        EmployeeRecordFactory(
            job_application=job_application1,
            asp_id=job_application1.to_siae.convention.asp_id,
            approval_number=job_application1.approval.number,
        )
        job_application2 = JobApplicationFactory(
            with_approval=True, approval=job_application1.approval, to_siae=job_application1.to_siae
        )
        assert job_application1.candidate_has_employee_record
        assert job_application2.candidate_has_employee_record

        # test job_application has one Approval and no EmployeeRecord
        # but an EmployeeRecord already exists for the same approval.number
        # in an other Siae
        job_application1 = JobApplicationFactory(with_approval=True)
        EmployeeRecordFactory(
            job_application=job_application1,
            asp_id=job_application1.to_siae.convention.asp_id,
            approval_number=job_application1.approval.number,
        )
        job_application2 = JobApplicationFactory(with_approval=True, approval=job_application1.approval)
        assert job_application1.candidate_has_employee_record
        assert not job_application2.candidate_has_employee_record

    def test_get_sender_kind_display(self):
        non_siae_items = [
            (JobApplicationSentBySiaeFactory(to_siae__kind=kind), "Employeur")
            for kind in [SiaeKind.EA, SiaeKind.EATT, SiaeKind.GEIQ, SiaeKind.OPCS]
        ]
        items = [
            [JobApplicationFactory(sent_by_authorized_prescriber_organisation=True), "Prescripteur"],
            [JobApplicationSentByPrescriberOrganizationFactory(), "Orienteur"],
            [JobApplicationSentBySiaeFactory(), "Employeur (SIAE)"],
            [JobApplicationSentByJobSeekerFactory(), "Demandeur d'emploi"],
        ] + non_siae_items

        for job_application, sender_kind_display in items:
            with self.subTest(sender_kind_display):
                assert job_application.get_sender_kind_display() == sender_kind_display

    def test_geiq_fields_validation(self):
        # Full clean
        with self.assertRaisesRegex(
            ValidationError, "Le nombre d'heures par semaine ne peut être saisi que pour un GEIQ"
        ):
            JobApplicationFactory(to_siae__kind=SiaeKind.EI, nb_hours_per_week=20)

        with self.assertRaisesRegex(
            ValidationError, "Les précisions sur le type de contrat ne peuvent être saisies que pour un GEIQ"
        ):
            JobApplicationFactory(to_siae__kind=SiaeKind.EI, contract_type_details="foo")

        with self.assertRaisesRegex(ValidationError, "Le type de contrat ne peut être saisi que pour un GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.EI, contract_type=ContractType.OTHER)

        # Constraints
        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(
                to_siae__kind=SiaeKind.GEIQ,
                contract_type=ContractType.PROFESSIONAL_TRAINING,
                contract_type_details="foo",
            )

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, nb_hours_per_week=1)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, contract_type=ContractType.OTHER)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, contract_type_details="foo")

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, contract_type_details="foo", nb_hours_per_week=1)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, contract_type=ContractType.OTHER, nb_hours_per_week=1)

        # Mind the parens in RE...
        with self.assertRaisesRegex(
            ValidationError, "Une candidature ne peut avoir les deux types de diagnostics \\(IAE et GEIQ\\)"
        ):
            JobApplicationFactory(
                with_geiq_eligibility_diagnosis=True, eligibility_diagnosis=EligibilityDiagnosisFactory()
            )

        # Validators
        with self.assertRaisesRegex(
            ValidationError,
            f"Assurez-vous que cette valeur est supérieure ou égale à {JobApplication.GEIQ_MIN_HOURS_PER_WEEK}.",
        ):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, nb_hours_per_week=0)

        with self.assertRaisesRegex(
            ValidationError,
            f"Assurez-vous que cette valeur est inférieure ou égale à {JobApplication.GEIQ_MAX_HOURS_PER_WEEK}.",
        ):
            JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, nb_hours_per_week=49)

        # Should pass: normal cases
        JobApplicationFactory()

        for contract_type in [ContractType.APPRENTICESHIP, ContractType.PROFESSIONAL_TRAINING]:
            with self.subTest(contract_type):
                JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, contract_type=contract_type, nb_hours_per_week=35)

        JobApplicationFactory(
            to_siae__kind=SiaeKind.GEIQ,
            contract_type=ContractType.OTHER,
            nb_hours_per_week=30,
            contract_type_details="foo",
        )

    def test_application_on_non_job_seeker(self):
        with self.assertRaisesRegex(
            ValidationError,
            "Impossible de candidater pour cet utilisateur, celui-ci n'est pas un compte candidat",
        ):
            JobApplicationFactory(job_seeker=PrescriberFactory())


def test_can_be_cancelled():
    assert JobApplicationFactory().can_be_cancelled is True


def test_can_be_cancelled_when_origin_is_ai_stock():
    assert JobApplicationFactory(origin=Origin.AI_STOCK).can_be_cancelled is False


def test_geiq_qualification_fields_contraint():
    with pytest.raises(
        Exception, match="Incohérence dans les champs concernant la qualification pour le contrat GEIQ"
    ):
        JobApplicationFactory(
            to_siae__kind=SiaeKind.GEIQ,
            qualification_type=QualificationType.STATE_DIPLOMA,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        )

    for qualification_type in [QualificationType.CQP, QualificationType.CCN]:
        JobApplicationFactory(
            to_siae__kind=SiaeKind.GEIQ,
            qualification_type=qualification_type,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        )


@pytest.mark.parametrize("status", Status)
def test_can_be_cancelled_when_an_employee_record_exists(status):
    job_application = JobApplicationFactory()
    BareEmployeeRecordFactory(job_application=job_application, status=status)
    assert job_application.can_be_cancelled is False


def test_can_have_prior_action():
    geiq = SiaeFactory.build(kind=SiaeKind.GEIQ)
    non_geiq = SiaeFactory.build(kind=SiaeKind.AI)

    assert (
        JobApplicationFactory.build(to_siae=geiq, state=JobApplicationWorkflow.STATE_NEW).can_have_prior_action
        is False
    )
    assert (
        JobApplicationFactory.build(to_siae=geiq, state=JobApplicationWorkflow.STATE_POSTPONED).can_have_prior_action
        is True
    )
    assert (
        JobApplicationFactory.build(
            to_siae=non_geiq, state=JobApplicationWorkflow.STATE_POSTPONED
        ).can_have_prior_action
        is False
    )


def test_can_change_prior_actions():
    geiq = SiaeFactory(kind=SiaeKind.GEIQ)
    non_geiq = SiaeFactory(kind=SiaeKind.ACI)

    assert (
        JobApplicationFactory.build(to_siae=geiq, state=JobApplicationWorkflow.STATE_NEW).can_change_prior_actions
        is False
    )
    assert (
        JobApplicationFactory.build(
            to_siae=geiq, state=JobApplicationWorkflow.STATE_POSTPONED
        ).can_change_prior_actions
        is True
    )
    assert (
        JobApplicationFactory.build(to_siae=geiq, state=JobApplicationWorkflow.STATE_ACCEPTED).can_change_prior_actions
        is False
    )
    assert (
        JobApplicationFactory.build(
            to_siae=non_geiq, state=JobApplicationWorkflow.STATE_POSTPONED
        ).can_change_prior_actions
        is False
    )


class JobApplicationQuerySetTest(TestCase):
    def test_created_in_past(self):
        now = timezone.now()
        hours_ago_10 = now - timezone.timedelta(hours=10)
        hours_ago_20 = now - timezone.timedelta(hours=20)
        hours_ago_30 = now - timezone.timedelta(hours=30)

        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_10)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_20)
        JobApplicationSentByJobSeekerFactory(created_at=hours_ago_30)

        assert JobApplication.objects.created_in_past(hours=5).count() == 0
        assert JobApplication.objects.created_in_past(hours=15).count() == 1
        assert JobApplication.objects.created_in_past(hours=25).count() == 2
        assert JobApplication.objects.created_in_past(hours=35).count() == 3

    def test_get_unique_fk_objects(self):
        # Create 3 job applications for 2 candidates to check
        # that `get_unique_fk_objects` returns 2 candidates.
        JobApplicationSentByJobSeekerFactory()
        job_seeker = JobSeekerFactory()
        JobApplicationSentByJobSeekerFactory.create_batch(2, job_seeker=job_seeker)

        unique_job_seekers = JobApplication.objects.get_unique_fk_objects("job_seeker")

        assert JobApplication.objects.count() == 3
        assert len(unique_job_seekers) == 2
        assert type(unique_job_seekers[0]) == User

    def test_with_has_suspended_approval(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_has_suspended_approval().get(pk=job_app.pk)
        assert hasattr(qs, "has_suspended_approval")
        assert not qs.has_suspended_approval

    def test_with_last_change(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        qs = JobApplication.objects.with_last_change().get(pk=job_app.pk)
        assert hasattr(qs, "last_change")
        assert qs.last_change == job_app.created_at

        job_app.process()
        qs = JobApplication.objects.with_last_change().get(pk=job_app.pk)
        last_change = job_app.logs.order_by("-timestamp").first()
        assert qs.last_change == last_change.timestamp

    def test_with_jobseeker_eligibility_diagnosis(self):
        job_app = JobApplicationFactory(with_approval=True)
        diagnosis = job_app.eligibility_diagnosis
        qs = JobApplication.objects.with_jobseeker_eligibility_diagnosis().get(pk=job_app.pk)
        assert qs.jobseeker_eligibility_diagnosis == diagnosis.pk

    def test_with_eligibility_diagnosis_criterion(self):
        job_app = JobApplicationFactory(with_approval=True, eligibility_diagnosis=None)
        diagnosis = EligibilityDiagnosisFactory(job_seeker=job_app.job_seeker, created_at=timezone.now())

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteriaLevel.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)

        older_diagnosis = EligibilityDiagnosisFactory(
            job_seeker=job_app.job_seeker, created_at=timezone.now() - relativedelta(months=1)
        )
        older_diagnosis.administrative_criteria.add(level1_other_criterion)

        qs = (
            JobApplication.objects.with_jobseeker_eligibility_diagnosis()
            .with_eligibility_diagnosis_criterion(level1_criterion.pk)
            .with_eligibility_diagnosis_criterion(level2_criterion.pk)
            .with_eligibility_diagnosis_criterion(level1_other_criterion.pk)
            .get(pk=job_app.pk)
        )
        # Check that with_jobseeker_eligibility_diagnosis works and retrieves the most recent diagnosis
        assert getattr(qs, f"eligibility_diagnosis_criterion_{level1_criterion.pk}")
        assert getattr(qs, f"eligibility_diagnosis_criterion_{level2_criterion.pk}")
        assert not getattr(qs, f"eligibility_diagnosis_criterion_{level1_other_criterion.pk}")

        job_app.eligibility_diagnosis = older_diagnosis
        job_app.save()

        qs = (
            JobApplication.objects.with_jobseeker_eligibility_diagnosis()
            .with_eligibility_diagnosis_criterion(level1_criterion.pk)
            .with_eligibility_diagnosis_criterion(level2_criterion.pk)
            .with_eligibility_diagnosis_criterion(level1_other_criterion.pk)
            .get(pk=job_app.pk)
        )
        # Check that with_jobseeker_eligibility_diagnosis uses job_app.eligibility_diagnosis in priority
        assert not getattr(qs, f"eligibility_diagnosis_criterion_{level1_criterion.pk}")
        assert not getattr(qs, f"eligibility_diagnosis_criterion_{level2_criterion.pk}")
        assert getattr(qs, f"eligibility_diagnosis_criterion_{level1_other_criterion.pk}")

    def test_with_list_related_data(self):
        job_app = JobApplicationFactory(with_approval=True)
        diagnosis = EligibilityDiagnosisFactory(job_seeker=job_app.job_seeker)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteriaLevel.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        criteria = [level1_criterion.pk, level2_criterion.pk, level1_other_criterion.pk]
        qs = JobApplication.objects.with_list_related_data(criteria).get(pk=job_app.pk)

        assert hasattr(qs, "approval")
        assert hasattr(qs, "job_seeker")
        assert hasattr(qs, "sender")
        assert hasattr(qs, "sender_siae")
        assert hasattr(qs, "sender_prescriber_organization")
        assert hasattr(qs, "to_siae")
        assert hasattr(qs, "selected_jobs")
        assert hasattr(qs, "has_suspended_approval")
        assert hasattr(qs, "jobseeker_eligibility_diagnosis")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level1_criterion.pk}")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level2_criterion.pk}")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level1_other_criterion.pk}")

    def test_eligible_as_employee_record(self):
        # Results must be a list of job applications:
        # Accepted
        job_app = JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # With an approval
        job_app = JobApplicationWithoutApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # Approval `create_employee_record` is False.
        job_app = JobApplicationWithApprovalNotCancellableFactory(create_employee_record=False)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # Must be accepted and only after CANCELLATION_DAYS_AFTER_HIRING_STARTED
        job_app = JobApplicationFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # Approval start date is also checked (must be older then CANCELLATION_DAY_AFTER_HIRING STARTED).
        job_app = JobApplicationWithApprovalNotCancellableFactory()
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # After employee record creation
        job_app = JobApplicationWithApprovalNotCancellableFactory()
        employee_record = EmployeeRecordFactory(
            job_application=job_app,
            asp_id=job_app.to_siae.convention.asp_id,
            approval_number=job_app.approval.number,
            status=Status.NEW,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        employee_record.status = Status.PROCESSED
        employee_record.save()
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # After employee record is disabled
        employee_record.update_as_disabled()
        assert employee_record.status == Status.DISABLED
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

        # Create a second job application to the same SIAE and for the same approval
        second_job_app = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            to_siae=job_app.to_siae,
            approval=job_app.approval,
        )
        assert second_job_app not in JobApplication.objects.eligible_as_employee_record(second_job_app.to_siae)

        # No employee record, but with a suspension
        job_app = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        SuspensionFactory(
            siae=job_app.to_siae,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        # No employee record, but with a prolongation
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        ProlongationFactory(
            declared_by_siae=job_app.to_siae,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        # No employee record, but with a prolongation and a suspension
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        SuspensionFactory(
            siae=job_app.to_siae,
            approval=job_app.approval,
        )
        ProlongationFactory(
            declared_by_siae=job_app.to_siae,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        # ...and with an employee record already existing for that employee
        EmployeeRecordFactory(
            status=Status.READY,
            job_application__to_siae=job_app.to_siae,
            approval_number=job_app.approval.number,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

    def test_eligible_job_applications_with_a_suspended_or_extended_approval_older_than_cutoff(self):
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)
        SuspensionFactory(
            siae=job_app.to_siae,
            approval=job_app.approval,
            created_at=timezone.make_aware(datetime.datetime(2001, 1, 1)),
        )
        ProlongationFactory(
            declared_by_siae=job_app.to_siae,
            approval=job_app.approval,
            created_at=timezone.make_aware(datetime.datetime(2001, 1, 1)),
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_siae)

    def test_with_accepted_at_for_created_from_pe_approval(self):
        JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            origin=Origin.PE_APPROVAL,
        )

        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at == job_application.created_at

    def test_with_accepted_at_for_accept_transition(self):
        job_application = JobApplicationSentBySiaeFactory()
        job_application.process()
        job_application.accept(user=job_application.sender)

        expected_created_at = JobApplicationTransitionLog.objects.filter(
            job_application=job_application,
            transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
        ).aggregate(timestamp=Max("timestamp"))["timestamp"]
        assert JobApplication.objects.with_accepted_at().first().accepted_at == expected_created_at

    def test_with_accepted_at_with_multiple_transitions(self):
        job_application = JobApplicationSentBySiaeFactory()
        job_application.process()
        job_application.accept(user=job_application.sender)
        job_application.cancel(user=job_application.sender)
        job_application.accept(user=job_application.sender)
        job_application.cancel(user=job_application.sender)

        expected_created_at = JobApplicationTransitionLog.objects.filter(
            job_application=job_application,
            transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
        ).aggregate(timestamp=Max("timestamp"))["timestamp"]
        # We should not have more job applications
        assert JobApplication.objects.with_accepted_at().count() == JobApplication.objects.count()
        assert JobApplication.objects.with_accepted_at().first().accepted_at == expected_created_at

    def test_with_accepted_at_default_value(self):
        job_application = JobApplicationSentBySiaeFactory()

        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.process()  # 1 transition but no accept
        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.refuse(job_application.sender)  # 2 transitions, still no accept
        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

    def test_with_accepted_at_for_accepted_with_no_transition(self):
        JobApplicationSentBySiaeFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at == job_application.created_at

    def test_with_accepted_at_for_ai_stock(self):
        JobApplicationFactory(origin=Origin.AI_STOCK)

        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at.date() == job_application.hiring_start_at
        assert job_application.accepted_at != job_application.created_at


class JobApplicationNotificationsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_siae(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            selected_jobs=Appellation.objects.all(),
        )
        email = NewQualifiedJobAppEmployersNotification(job_application=job_application).email
        # To.
        assert job_application.to_siae.members.first().email in email.to
        assert len(email.to) == 1

        # Body.
        assert job_application.job_seeker.first_name in email.body
        assert job_application.job_seeker.last_name in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.sender.get_full_name() in email.body
        assert job_application.sender.email in email.body
        assert format_filters.format_phone(job_application.sender.phone) in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.to_siae.city in email.body
        assert str(job_application.to_siae.pk) in email.body
        assert job_application.resume_link in email.body

    def test_new_for_prescriber(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, selected_jobs=Appellation.objects.all()
        )
        email = job_application.email_new_for_prescriber
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        assert job_application.sender_kind == SenderKind.PRESCRIBER

        # Subject
        assert job_application.job_seeker.get_full_name() in email.subject

        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.title() in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.sender.get_full_name().title() in email.body
        assert job_application.sender.email in email.body
        assert format_filters.format_phone(job_application.sender.phone) in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.to_siae.kind in email.body
        assert job_application.to_siae.city in email.body

        # Assert the Job Seeker does not have access to confidential information.
        email = job_application.email_new_for_job_seeker()
        assert job_application.sender.get_full_name().title() in email.body
        assert job_application.sender_prescriber_organization.display_name in email.body
        assert job_application.sender.email not in email.body
        assert format_filters.format_phone(job_application.sender.phone) not in email.body
        assert job_application.resume_link in email.body

    def test_new_for_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory(selected_jobs=Appellation.objects.all())
        email = job_application.email_new_for_job_seeker()
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        assert job_application.sender_kind == SenderKind.JOB_SEEKER

        # Subject
        assert job_application.to_siae.display_name in email.subject

        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.title() in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.sender.first_name.title() in email.body
        assert job_application.sender.last_name.title() in email.body
        assert job_application.sender.email in email.body
        assert format_filters.format_phone(job_application.sender.phone) in email.body
        assert job_application.to_siae.display_name in email.body
        assert reverse("login:job_seeker") in email.body
        assert reverse("account_reset_password") in email.body
        assert job_application.resume_link in email.body

    def test_accept_for_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        email = job_application.email_accept_for_job_seeker
        # To.
        assert job_application.job_seeker.email == job_application.sender.email
        assert job_application.job_seeker.email in email.to
        assert len(email.to) == 1
        assert len(email.bcc) == 0
        # Subject.
        assert "Candidature acceptée" in email.subject
        # Body.
        assert job_application.to_siae.display_name in email.body
        assert job_application.answer in email.body

    def test_accept_for_proxy(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        email = job_application.email_accept_for_proxy
        # To.
        assert job_application.to_siae.email not in email.to
        assert email.to == [job_application.sender.email]
        assert len(email.to) == 1
        assert len(email.bcc) == 0
        # Subject.
        assert "Candidature acceptée et votre avis sur les emplois de l'inclusion" in email.subject
        # Body.
        assert title(job_application.job_seeker.get_full_name()) in email.body
        assert title(job_application.sender.get_full_name()) in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.answer in email.body
        assert "Date de début du contrat" in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert "Date de fin du contrat" in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert job_application.sender_prescriber_organization.accept_survey_url in email.body

    def test_accept_for_proxy_without_hiring_end_at(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, hiring_end_at=None)
        email = job_application.email_accept_for_proxy
        assert "Date de fin du contrat : Non renseigné" in email.body

    def test_accept_trigger_manual_approval(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=datetime.date.today(),
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        # To.
        assert settings.ITOU_EMAIL_CONTACT in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.job_seeker.first_name in email.body
        assert job_application.job_seeker.last_name in email.body
        assert job_application.job_seeker.email in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.to_siae.siret in email.body
        assert job_application.to_siae.kind in email.body
        assert job_application.to_siae.get_kind_display() in email.body
        assert job_application.to_siae.get_department_display() in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert accepted_by.get_full_name() in email.body
        assert accepted_by.email in email.body
        assert reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk]) in email.body

    def test_accept_trigger_manual_approval_without_hiring_end_at(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=datetime.date.today(),
            hiring_end_at=None,
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        assert "Date de fin du contrat : Non renseigné" in email.body

    def test_refuse(self):

        # When sent by authorized prescriber.
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.email_refuse_for_proxy
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.sender.first_name.title() in email.body
        assert job_application.sender.last_name.title() in email.body
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.title() in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.answer in email.body
        assert job_application.answer_to_prescriber in email.body

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.email_refuse_for_job_seeker
        # To.
        assert job_application.job_seeker.email == job_application.sender.email
        assert job_application.job_seeker.email in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.to_siae.display_name in email.body
        assert job_application.answer in email.body
        assert job_application.answer_to_prescriber not in email.body

    def test_email_deliver_approval(self):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=approval,
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_deliver_approval(accepted_by)
        # To.
        assert accepted_by.email in email.to
        assert len(email.to) == 1
        # Body.
        assert approval.user.get_full_name() in email.subject
        assert approval.number_with_spaces in email.body
        assert approval.start_at.strftime("%d/%m/%Y") in email.body
        assert f"{approval.remainder.days} jours" in email.body
        assert approval.user.last_name in email.body
        assert approval.user.first_name in email.body
        assert approval.user.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert job_application.to_siae.display_name in email.body
        assert job_application.to_siae.get_kind_display() in email.body
        assert job_application.to_siae.address_line_1 in email.body
        assert job_application.to_siae.address_line_2 in email.body
        assert job_application.to_siae.post_code in email.body
        assert job_application.to_siae.city in email.body
        assert global_constants.ITOU_ASSISTANCE_URL in email.body
        assert job_application.to_siae.accept_survey_url in email.body

    def test_email_deliver_approval_without_hiring_end_at(self):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval=approval,
            hiring_end_at=None,
        )
        accepted_by = job_application.to_siae.members.first()
        email = job_application.email_deliver_approval(accepted_by)
        assert "Se terminant le : Non renseigné" in email.body

    def test_email_deliver_approval_when_subject_to_eligibility_rules(self):
        job_application = JobApplicationFactory(with_approval=True, to_siae__subject_to_eligibility=True)

        email = job_application.email_deliver_approval(job_application.to_siae.members.first())

        assert (
            f"PASS IAE pour {job_application.job_seeker.get_full_name()} et avis sur les emplois de l'inclusion"
            == email.subject
        )
        assert "PASS IAE" in email.body

    def test_email_deliver_approval_when_not_subject_to_eligibility_rules(self):
        job_application = JobApplicationFactory(with_approval=True, to_siae__not_subject_to_eligibility=True)

        email = job_application.email_deliver_approval(job_application.to_siae.members.first())

        assert "Confirmation de l'embauche" == email.subject
        assert "PASS IAE" not in email.body
        assert global_constants.ITOU_ASSISTANCE_URL in email.body

    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_manually_deliver_approval(self, *args, **kwargs):
        staff_member = ItouStaffFactory()
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval=approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_deliver_approval(delivered_by=staff_member)
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_number_sent_at is not None
        assert job_application.approval_manually_delivered_by == staff_member
        assert job_application.approval_manually_refused_at is None
        assert job_application.approval_manually_refused_by is None
        assert len(mail.outbox) == 1

    def test_manually_refuse_approval(self):
        staff_member = ItouStaffFactory()
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        mail.outbox = []  # Delete previous emails.
        job_application.manually_refuse_approval(refused_by=staff_member)
        assert job_application.approval_manually_refused_by == staff_member
        assert job_application.approval_manually_refused_at is not None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_manually_delivered_by is None
        assert job_application.approval_number_sent_at is None
        assert len(mail.outbox) == 1

    def test_cancel(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationWorkflow.STATE_ACCEPTED
        )

        cancellation_user = job_application.to_siae.active_members.first()
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        assert cancellation_user.email in email.to
        assert job_application.sender.email in email.bcc
        assert len(email.to) == 1
        assert len(email.bcc) == 1
        # Body.
        assert "annulée" in email.body
        assert job_application.sender.first_name in email.body
        assert job_application.sender.last_name in email.body
        assert job_application.job_seeker.first_name in email.body
        assert job_application.job_seeker.last_name in email.body

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        email = job_application.email_cancel(cancelled_by=cancellation_user)
        # To.
        assert not email.bcc


class NewQualifiedJobAppEmployersNotificationTest(TestCase):
    def test_one_selected_job(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_descriptions = siae.job_description_through.all()

        selected_job = job_descriptions[0]
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])

        membership = siae.siaemembership_set.first()
        assert not membership.notifications
        NewQualifiedJobAppEmployersNotification.subscribe(recipient=membership, subscribed_pks=[selected_job.pk])
        assert NewQualifiedJobAppEmployersNotification.is_subscribed(
            recipient=membership, subscribed_pk=selected_job.pk
        )

        # Receiver is now subscribed to one kind of notification
        assert len(NewQualifiedJobAppEmployersNotification._get_recipient_subscribed_pks(recipient=membership)) == 1

        # A job application is sent concerning another job_description.
        # He should then be subscribed to two different notifications.
        selected_job = job_descriptions[1]
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])

        NewQualifiedJobAppEmployersNotification.subscribe(recipient=membership, subscribed_pks=[selected_job.pk])
        assert NewQualifiedJobAppEmployersNotification.is_subscribed(
            recipient=membership, subscribed_pk=selected_job.pk
        )

        assert len(NewQualifiedJobAppEmployersNotification._get_recipient_subscribed_pks(recipient=membership)) == 2
        assert len(membership.notifications) == 1

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        recipients = notification.recipients_emails
        assert len(recipients) == 1

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

        assert len(notification.recipients_emails) == 2

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
        assert len(recipients) == siae.members.count()

    def test_unsubscribe(self):
        siae = SiaeWithMembershipAndJobsFactory()
        selected_job = siae.job_description_through.first()
        job_application = JobApplicationFactory(to_siae=siae, selected_jobs=[selected_job])
        assert siae.members.count() == 1

        recipient = siae.siaemembership_set.first()

        NewQualifiedJobAppEmployersNotification.subscribe(recipient=recipient, subscribed_pks=[selected_job.pk])
        assert NewQualifiedJobAppEmployersNotification.is_subscribed(
            recipient=recipient, subscribed_pk=selected_job.pk
        )

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        assert len(notification.recipients_emails) == 1

        NewQualifiedJobAppEmployersNotification.unsubscribe(recipient=recipient, subscribed_pks=[selected_job.pk])
        assert not NewQualifiedJobAppEmployersNotification.is_subscribed(
            recipient=recipient, subscribed_pk=selected_job.pk
        )

        notification = NewQualifiedJobAppEmployersNotification(job_application=job_application)
        assert len(notification.recipients_emails) == 0


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
        assert job_seeker.pole_emploi_id != ""

        kwargs = {
            "job_seeker": job_seeker,
            "sender": job_seeker,
            "sender_kind": SenderKind.JOB_SEEKER,
        }
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_NEW, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)

        assert job_seeker.job_applications.count() == 4
        assert job_seeker.job_applications.pending().count() == 4

        job_application = job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_PROCESSING).first()
        job_application.accept(user=job_application.to_siae.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count() == 1
        assert job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).count() == 3

        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[1].subject
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_obsolete(self, notify_mock):
        """
        An obsolete job application can be accepted.
        """
        job_seeker = JobSeekerFactory()

        kwargs = {
            "job_seeker": job_seeker,
            "sender": job_seeker,
            "sender_kind": SenderKind.JOB_SEEKER,
        }
        for state in [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_OBSOLETE,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]:
            JobApplicationFactory(state=state, **kwargs)

        assert job_seeker.job_applications.count() == 6

        job_application = job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).first()
        job_application.accept(user=job_application.to_siae.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED).count() == 2
        assert job_seeker.job_applications.filter(state=JobApplicationWorkflow.STATE_OBSOLETE).count() == 4

        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[1].subject
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
        assert job_application.approval is not None
        assert job_application.approval.number == pe_approval.number
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin == Origin.PE_APPROVAL
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[1].subject
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
        assert job_application.approval is not None
        assert job_application.approval.number == pe_approval.number
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin == Origin.PE_APPROVAL
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[1].subject
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
        assert job_application.approval is None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_MANUAL
        # Check sent email.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the team.
        assert "PASS IAE requis sur Itou" in mail.outbox[1].subject
        # no approval, so no notification sent to pole emploi
        notify_mock.assert_not_called()

    def test_accept_job_application_sent_by_job_seeker_with_a_nir_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            pole_emploi_id="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_with_a_pole_emploi_id_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            nir="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_job_seeker_unregistered_no_pe_approval(self, notify_mock):
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_NOT_REGISTERED
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_prescriber(self, notify_mock):
        """
        Accept a job application sent by an "orienteur".
        """
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.pole_emploi_id != ""
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent email.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.accept_email_subject_proxy in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[2].subject
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_accept_job_application_sent_by_authorized_prescriber(self, notify_mock):
        """
        Accept a job application sent by an authorized prescriber.
        """
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.pole_emploi_id != ""
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.to_siae.is_subject_to_eligibility_rules
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent email.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.accept_email_subject_proxy in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[2].subject
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
        assert approval.is_in_waiting_period
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=user,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.pole_emploi_id != ""
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent emails.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.accept_email_subject_proxy in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[2].subject
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
        assert approval.is_in_waiting_period
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=user,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            eligibility_diagnosis=None,
        )
        with pytest.raises(xwf_models.AbortTransition):
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
        assert approval.is_in_waiting_period

        diagnosis = EligibilityDiagnosisFactory(job_seeker=user)
        assert diagnosis.is_valid

        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=user, state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.sent_pass_email_subject in mail.outbox[1].subject
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
        assert job_application.job_seeker.pole_emploi_id != ""
        job_application.accept(user=job_application.to_siae.members.first())
        assert job_application.to_siae.is_subject_to_eligibility_rules
        assert job_application.approval is None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == ""
        # Check sent email (no notification of approval).
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.accept_email_subject_proxy in mail.outbox[1].subject
        # No approval, so no notification is sent to Pole Emploi
        notify_mock.assert_not_called()

    def test_accept_job_application_by_siae_not_subject_to_eligibility_rules(self, notify_mock):
        """
        No approval should be delivered for an employer not subject to eligibility rules.
        """
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_siae__kind=SiaeKind.GEIQ,
        )
        job_application.accept(user=job_application.to_siae.members.first())
        assert not job_application.to_siae.is_subject_to_eligibility_rules
        assert job_application.approval is None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == ""
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.accept_email_subject_job_seeker in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.accept_email_subject_proxy in mail.outbox[1].subject
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
            eligibility_diagnosis=None,
        )

        to_siae = job_application.to_siae
        to_siae_staff_member = to_siae.members.first()
        job_seeker = job_application.job_seeker

        eligibility_diagnosis = EligibilityDiagnosisMadeBySiaeFactory(
            job_seeker=job_seeker, author=to_siae_staff_member, author_siae=to_siae
        )

        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_seeker.pole_emploi_id != ""

        job_application.accept(user=to_siae_staff_member)
        assert job_application.to_siae.is_subject_to_eligibility_rules
        assert job_application.eligibility_diagnosis == eligibility_diagnosis
        # Approval delivered -> Pole Emploi is notified
        notify_mock.assert_called()

    def test_refuse(self, notify_mock):
        user = JobSeekerFactory()
        kwargs = {"job_seeker": user, "sender": user, "sender_kind": SenderKind.JOB_SEEKER}

        JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationWorkflow.STATE_POSTPONED, **kwargs)

        assert user.job_applications.count() == 2
        assert user.job_applications.pending().count() == 2

        for job_application in user.job_applications.all():
            job_application.refuse()
            # Check sent email.
            assert len(mail.outbox) == 1
            assert "Candidature déclinée" in mail.outbox[0].subject
            mail.outbox = []
            # Approval refused -> Pole Emploi is not notified, because they don’t care
            notify_mock.assert_not_called()

    def test_cancel_delete_linked_approval(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)
        assert job_application.job_seeker.approvals.count() == 1
        assert JobApplication.objects.filter(approval=job_application.approval).count() == 1

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        assert job_application.state == JobApplicationWorkflow.STATE_CANCELLED

        job_application.refresh_from_db()
        assert not job_application.approval

    def test_cancel_do_not_delete_linked_approval(self, *args, **kwargs):

        # The approval is linked to two accepted job applications
        job_application = JobApplicationFactory(with_approval=True)
        approval = job_application.approval
        JobApplicationFactory(with_approval=True, approval=approval, job_seeker=job_application.job_seeker)

        assert job_application.job_seeker.approvals.count() == 1
        assert JobApplication.objects.filter(approval=approval).count() == 2

        cancellation_user = job_application.to_siae.active_members.first()
        job_application.cancel(user=cancellation_user)

        assert job_application.state == JobApplicationWorkflow.STATE_CANCELLED

        job_application.refresh_from_db()
        assert job_application.approval

    def test_cancellation_not_allowed(self, *args, **kwargs):
        today = datetime.date.today()

        # Linked employee record with blocking status
        job_application = JobApplicationFactory(with_approval=True, hiring_start_at=(today - relativedelta(days=365)))
        cancellation_user = job_application.to_siae.active_members.first()
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        # xworkflows.base.AbortTransition
        with pytest.raises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)

        # Wrong state
        job_application = JobApplicationFactory(
            with_approval=True, hiring_start_at=today, state=JobApplicationWorkflow.STATE_NEW
        )
        cancellation_user = job_application.to_siae.active_members.first()
        with pytest.raises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)


class JobApplicationCsvExportTest(TestCase):
    @patch("itou.job_applications.models.huey_notify_pole_emploi")
    def test_xlsx_export_contains_the_necessary_info(self, *args, **kwargs):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_seeker = JobSeekerFactory()
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            selected_jobs=Appellation.objects.all(),
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_siae.members.first())

        # The accept transition above will create a valid PASS IAE for the job seeker.
        assert job_seeker.approvals.last().is_valid

        response = stream_xlsx_export(JobApplication.objects.all(), "filename")
        assert get_rows_from_streaming_response(response) == [
            JOB_APPLICATION_CSV_HEADERS,
            [
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                job_seeker.birthdate.strftime("%d/%m/%Y"),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_siae.display_name,
                str(job_application.to_siae.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                job_application.created_at.strftime("%d/%m/%Y"),
                "Candidature acceptée",
                job_application.hiring_start_at.strftime("%d/%m/%Y"),
                job_application.hiring_end_at.strftime("%d/%m/%Y"),
                "",  # no reafusal reason
                "oui",  # Eligibility status.
                job_application.approval.number,
                job_application.approval.start_at.strftime("%d/%m/%Y"),
                job_application.approval.end_at.strftime("%d/%m/%Y"),
            ],
        ]

    def test_refused_job_application_has_reason_in_xlsx_export(self):
        job_seeker = JobSeekerFactory()
        kwargs = {
            "job_seeker": job_seeker,
            "sender": job_seeker,
            "sender_kind": SenderKind.JOB_SEEKER,
            "refusal_reason": RefusalReason.DID_NOT_COME,
        }

        job_application = JobApplicationFactory(state=JobApplicationWorkflow.STATE_PROCESSING, **kwargs)
        job_application.refuse()

        response = stream_xlsx_export(JobApplication.objects.all(), "filename")
        assert get_rows_from_streaming_response(response) == [
            JOB_APPLICATION_CSV_HEADERS,
            [
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                job_seeker.birthdate.strftime("%d/%m/%Y"),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_siae.display_name,
                str(job_application.to_siae.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                job_application.created_at.strftime("%d/%m/%Y"),
                "Candidature déclinée",
                job_application.hiring_start_at.strftime("%d/%m/%Y"),
                job_application.hiring_end_at.strftime("%d/%m/%Y"),
                "Candidat non joignable",
                "oui",
                "",
                "",
                "",
            ],
        ]


class JobApplicationAdminFormTest(TestCase):
    def test_job_application_admin_form_validation(self):

        form_fields_list = [
            "job_seeker",
            "eligibility_diagnosis",
            "geiq_eligibility_diagnosis",
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
            "origin",
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
            "prehiring_guidance_days",
            "contract_type",
            "nb_hours_per_week",
            "contract_type_details",
            "qualification_type",
            "qualification_level",
            "planned_training_hours",
        ]
        form = JobApplicationAdminForm()
        assert list(form.fields.keys()) == form_fields_list

        # mandatory fields : job_seeker, to_siae
        form_errors = {
            "job_seeker": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "to_siae": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "state": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "origin": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "created_at": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "__all__": [{"message": "Emetteur prescripteur manquant.", "code": ""}],
        }

        data = {"sender_kind": SenderKind.PRESCRIBER}
        form = JobApplicationAdminForm(data)
        assert form.errors.as_json() == json.dumps(form_errors)

    def test_applications_sent_by_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        sender = job_application.sender
        sender_kind = job_application.sender_kind
        sender_siae = job_application.sender_siae

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur candidat manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_kind = SenderKind.PRESCRIBER
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur du mauvais type."] == form.errors["__all__"]
        job_application.sender_kind = sender_kind

        job_application.sender_siae = JobApplicationSentBySiaeFactory().sender_siae
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_siae = sender_siae

        job_application.sender_prescriber_organization = (
            JobApplicationSentByPrescriberOrganizationFactory().sender_prescriber_organization
        )
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Organisation du prescripteur émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_prescriber_organization = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_applications_sent_by_siae(self):
        job_application = JobApplicationSentBySiaeFactory()
        sender_siae = job_application.sender_siae
        sender = job_application.sender

        job_application.sender_siae = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice manquante."] == form.errors["__all__"]
        job_application.sender_siae = sender_siae

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur du mauvais type."] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur SIAE manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_prescriber_organization = (
            JobApplicationSentByPrescriberOrganizationFactory().sender_prescriber_organization
        )
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Organisation du prescripteur émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_prescriber_organization = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_applications_sent_by_prescriber_with_organization(self):
        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        sender = job_application.sender
        sender_prescriber_organization = job_application.sender_prescriber_organization

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur du mauvais type."] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur prescripteur manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Organisation du prescripteur émettrice manquante."] == form.errors["__all__"]
        job_application.sender_prescriber_organization = sender_prescriber_organization

        job_application.sender_siae = JobApplicationSentBySiaeFactory().sender_siae
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_siae = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_applications_sent_by_prescriber_without_organization(self):
        job_application = JobApplicationSentByPrescriberFactory()
        sender = job_application.sender

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur du mauvais type."] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Emetteur prescripteur manquant."] == form.errors["__all__"]
        job_application.sender = sender

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

        # explicit redundant test
        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_application_on_non_job_seeker(self):
        job_application = JobApplicationFactory()
        job_application.job_seeker = PrescriberFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Impossible de candidater pour cet utilisateur, celui-ci n'est pas un compte candidat"] == form.errors[
            "__all__"
        ]


class JobApplicationsEnumsTest(TestCase):
    def test_refusal_reason(self):
        """Some reasons are kept for history but not displayed to end users."""
        hidden_choices = RefusalReason.hidden()
        for choice in hidden_choices:
            reasons = [choice[0] for choice in RefusalReason.displayed_choices()]
            assert len(reasons) > 0
            with self.subTest(choice):
                assert choice.value not in reasons


class DisplayMissingEligibilityDiagnosesCommandTest(TestCase):
    def test_nominal(self):
        stdout = io.StringIO()
        user = ItouStaffFactory(email="batman@batcave.org")
        ja = JobApplicationFactory(
            with_approval=True,
            eligibility_diagnosis=None,
            approval__number="XXXXX1234567",
            approval__created_by=user,
        )
        management.call_command("display_missing_eligibility_diagnoses", stdout=stdout)
        assert stdout.getvalue().split("\n") == [
            "number,created_at,started_at,end_at,created_by,job_seeker",
            f"{ja.approval.number},{ja.approval.created_at.isoformat()},{ja.approval.start_at},"
            f"{ja.approval.end_at},{ja.approval.created_by},{ja.approval.user}",
            "",
        ]
