import datetime
import json

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.forms.models import model_to_dict
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models
from freezegun import freeze_time

from itou.approvals.models import Approval, CancelledApproval
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.enums import (
    GEIQ_MAX_HOURS_PER_WEEK,
    GEIQ_MIN_HOURS_PER_WEEK,
    JobApplicationState,
    Origin,
    QualificationLevel,
    QualificationType,
    RefusalReason,
    SenderKind,
)
from itou.job_applications.export import JOB_APPLICATION_CSV_HEADERS, _resolve_title, stream_xlsx_export
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.users.enums import LackOfPoleEmploiId, Title
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.templatetags import format_filters
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
    ProlongationFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.employee_record.factories import BareEmployeeRecordFactory, EmployeeRecordFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithoutApprovalFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import ItouStaffFactory, JobSeekerFactory, PrescriberFactory
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
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
            eligibility_diagnosis=None,
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        assert not has_considered_valid_diagnoses
        assert not job_application.eligibility_diagnosis_by_siae_required

        job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.EI,
            eligibility_diagnosis=None,
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        assert not has_considered_valid_diagnoses
        assert job_application.eligibility_diagnosis_by_siae_required

    def test_accepted_by(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
        )
        user = job_application.to_company.members.first()
        job_application.accept(user=user)
        assert job_application.accepted_by == user

    def test_refused_by(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
        )
        user = job_application.to_company.members.first()
        job_application.refuse(user=user)
        assert job_application.refused_by == user

    def test_is_sent_by_authorized_prescriber(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        assert not job_application.is_sent_by_authorized_prescriber
        job_application = JobApplicationSentByPrescriberFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationSentByPrescriberOrganizationFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationSentByCompanyFactory()
        assert not job_application.is_sent_by_authorized_prescriber

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        assert job_application.is_sent_by_authorized_prescriber

    def test_is_refused_for_other_reason(self):
        job_application = JobApplicationFactory()
        for state in JobApplicationState.values:
            for refusal_reason in RefusalReason.values:
                with self.subTest(
                    "Test state and refusal_reason permutations", state=state, refusal_reason=refusal_reason
                ):
                    job_application.state = state
                    job_application.refusal_reason = refusal_reason

                    if state == JobApplicationState.REFUSED and refusal_reason == RefusalReason.OTHER:
                        assert job_application.is_refused_for_other_reason
                    else:
                        assert not job_application.is_refused_for_other_reason

    def test_can_be_archived(self):
        """
        Only cancelled, refused and obsolete job_applications can be archived.
        """
        states_transition_not_possible = [
            JobApplicationState.NEW,
            JobApplicationState.PROCESSING,
            JobApplicationState.POSTPONED,
            JobApplicationState.ACCEPTED,
        ]
        states_transition_possible = [
            JobApplicationState.CANCELLED,
            JobApplicationState.REFUSED,
            JobApplicationState.OBSOLETE,
        ]

        for state in states_transition_not_possible:
            job_application = JobApplicationFactory(state=state)
            assert not job_application.can_be_archived

        for state in states_transition_possible:
            job_application = JobApplicationFactory(state=state)
            assert job_application.can_be_archived

    def test_get_sender_kind_display(self):
        non_siae_items = [
            (JobApplicationSentByCompanyFactory(to_company__kind=kind), "Employeur")
            for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.GEIQ, CompanyKind.OPCS]
        ]
        items = [
            [JobApplicationFactory(sent_by_authorized_prescriber_organisation=True), "Prescripteur"],
            [JobApplicationSentByPrescriberOrganizationFactory(), "Orienteur"],
            [JobApplicationSentByCompanyFactory(), "Employeur (SIAE)"],
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
            JobApplicationFactory(to_company__kind=CompanyKind.EI, nb_hours_per_week=20)

        with self.assertRaisesRegex(
            ValidationError, "Les précisions sur le type de contrat ne peuvent être saisies que pour un GEIQ"
        ):
            JobApplicationFactory(to_company__kind=CompanyKind.EI, contract_type_details="foo")

        with self.assertRaisesRegex(ValidationError, "Le type de contrat ne peut être saisi que pour un GEIQ"):
            JobApplicationFactory(to_company__kind=CompanyKind.EI, contract_type=ContractType.OTHER)

        # Constraints
        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(
                to_company__kind=CompanyKind.GEIQ,
                contract_type=ContractType.PROFESSIONAL_TRAINING,
                contract_type_details="foo",
            )

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, nb_hours_per_week=1)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, contract_type=ContractType.OTHER)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, contract_type_details="foo")

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, contract_type_details="foo", nb_hours_per_week=1)

        with self.assertRaisesRegex(ValidationError, "Incohérence dans les champs concernant le contrat GEIQ"):
            JobApplicationFactory(
                to_company__kind=CompanyKind.GEIQ, contract_type=ContractType.OTHER, nb_hours_per_week=1
            )

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
            f"Assurez-vous que cette valeur est supérieure ou égale à {GEIQ_MIN_HOURS_PER_WEEK}.",
        ):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, nb_hours_per_week=0)

        with self.assertRaisesRegex(
            ValidationError,
            f"Assurez-vous que cette valeur est inférieure ou égale à {GEIQ_MAX_HOURS_PER_WEEK}.",
        ):
            JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, nb_hours_per_week=49)

        # Should pass: normal cases
        JobApplicationFactory()

        for contract_type in [ContractType.APPRENTICESHIP, ContractType.PROFESSIONAL_TRAINING]:
            with self.subTest(contract_type):
                JobApplicationFactory(
                    to_company__kind=CompanyKind.GEIQ, contract_type=contract_type, nb_hours_per_week=35
                )

        JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
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

    def test_inverted_vae_contract(self):
        JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, inverted_vae_contract=True)
        JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, inverted_vae_contract=False)
        JobApplicationFactory(to_company__kind=CompanyKind.EI, inverted_vae_contract=None)
        with self.assertRaisesRegex(
            ValidationError, "Un contrat associé à une VAE inversée n'est possible que pour les GEIQ"
        ):
            JobApplicationFactory(to_company__kind=CompanyKind.AI, inverted_vae_contract=True)


def test_can_be_cancelled():
    assert JobApplicationFactory().can_be_cancelled is True


def test_can_be_cancelled_when_origin_is_ai_stock():
    assert JobApplicationFactory(origin=Origin.AI_STOCK).can_be_cancelled is False


def test_geiq_qualification_fields_contraint():
    with pytest.raises(
        Exception, match="Incohérence dans les champs concernant la qualification pour le contrat GEIQ"
    ):
        JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            qualification_type=QualificationType.STATE_DIPLOMA,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        )

    for qualification_type in [QualificationType.CQP, QualificationType.CCN]:
        JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            qualification_type=qualification_type,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        )


@pytest.mark.parametrize("status", Status)
def test_can_be_cancelled_when_an_employee_record_exists(status):
    job_application = JobApplicationFactory()
    BareEmployeeRecordFactory(job_application=job_application, status=status)
    assert job_application.can_be_cancelled is False


def test_can_have_prior_action():
    geiq = CompanyFactory.build(kind=CompanyKind.GEIQ)
    non_geiq = CompanyFactory.build(kind=CompanyKind.AI)

    assert JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.NEW).can_have_prior_action is False
    assert (
        JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.POSTPONED).can_have_prior_action is True
    )
    assert (
        JobApplicationFactory.build(to_company=non_geiq, state=JobApplicationState.POSTPONED).can_have_prior_action
        is False
    )


def test_can_change_prior_actions():
    geiq = CompanyFactory(kind=CompanyKind.GEIQ)
    non_geiq = CompanyFactory(kind=CompanyKind.ACI)

    assert (
        JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.NEW).can_change_prior_actions is False
    )
    assert (
        JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.POSTPONED).can_change_prior_actions
        is True
    )
    assert (
        JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.ACCEPTED).can_change_prior_actions
        is False
    )
    assert (
        JobApplicationFactory.build(to_company=non_geiq, state=JobApplicationState.POSTPONED).can_change_prior_actions
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
        # Create 3 job applications and 3 approvals for 2 candidates
        JobApplicationWithApprovalNotCancellableFactory()
        approval = ApprovalFactory(expired=True)
        JobApplicationWithApprovalNotCancellableFactory(job_seeker=approval.user)
        JobApplicationSentByJobSeekerFactory(job_seeker=approval.user)

        unique_job_seekers = JobApplication.objects.get_unique_fk_objects("job_seeker")
        assert JobApplication.objects.count() == 3
        assert len(unique_job_seekers) == 2
        assert isinstance(unique_job_seekers[0], User)

        unique_approvals = JobApplication.objects.get_unique_fk_objects("approval")
        assert Approval.objects.count() == 3
        assert len(unique_approvals) == 2
        assert isinstance(unique_approvals[0], Approval)

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
        diagnosis = EligibilityDiagnosisFactory(created_at=timezone.now())
        job_app = JobApplicationFactory(
            with_approval=True, job_seeker=diagnosis.job_seeker, eligibility_diagnosis=diagnosis
        )

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
        assert hasattr(qs, "sender_company")
        assert hasattr(qs, "sender_prescriber_organization")
        assert hasattr(qs, "to_company")
        assert hasattr(qs, "selected_jobs")
        assert hasattr(qs, "jobseeker_eligibility_diagnosis")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level1_criterion.pk}")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level2_criterion.pk}")
        assert hasattr(qs, f"eligibility_diagnosis_criterion_{level1_other_criterion.pk}")

    def test_eligible_as_employee_record(self):
        # Results must be a list of job applications:
        # Accepted
        job_app = JobApplicationFactory(state=JobApplicationState.NEW)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # With an approval
        job_app = JobApplicationWithoutApprovalFactory(state=JobApplicationState.ACCEPTED)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # Approval `create_employee_record` is False.
        job_app = JobApplicationWithApprovalNotCancellableFactory(create_employee_record=False)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # Must be accepted and only after CANCELLATION_DAYS_AFTER_HIRING_STARTED
        job_app = JobApplicationFactory(state=JobApplicationState.ACCEPTED)
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # Approval start date is also checked (must be older then CANCELLATION_DAY_AFTER_HIRING STARTED).
        job_app = JobApplicationWithApprovalNotCancellableFactory()
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # After employee record creation
        job_app = JobApplicationWithApprovalNotCancellableFactory()
        employee_record = EmployeeRecordFactory(
            job_application=job_app,
            asp_id=job_app.to_company.convention.asp_id,
            approval_number=job_app.approval.number,
            status=Status.NEW,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        employee_record.status = Status.PROCESSED
        employee_record.save()
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # After employee record is disabled
        employee_record.update_as_disabled()
        assert employee_record.status == Status.DISABLED
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

        # Create a second job application to the same SIAE and for the same approval
        second_job_app = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            to_company=job_app.to_company,
            approval=job_app.approval,
        )
        assert second_job_app not in JobApplication.objects.eligible_as_employee_record(second_job_app.to_company)
        # Create a third job application to an antenna SIAE
        third_job_app = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            to_company__convention=job_app.to_company.convention,
            to_company__source=Company.SOURCE_USER_CREATED,
            approval=job_app.approval,
        )
        assert third_job_app not in JobApplication.objects.eligible_as_employee_record(third_job_app.to_company)

        # No employee record, but with a suspension
        job_app = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        SuspensionFactory(
            siae=job_app.to_company,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        # No employee record, but with a suspension, and `create_employee_record` is False
        job_app = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=None,
            create_employee_record=False,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        SuspensionFactory(
            siae=job_app.to_company,
            approval=job_app.approval,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        # No employee record, but with a prolongation
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        ProlongationFactory(
            declared_by_siae=job_app.to_company,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        # No employee record, but with a prolongation, and `create_employee_record` is False
        job_app = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=None,
            create_employee_record=False,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        ProlongationFactory(
            declared_by_siae=job_app.to_company,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        # No employee record, but with a prolongation and a suspension
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        SuspensionFactory(
            siae=job_app.to_company,
            approval=job_app.approval,
        )
        ProlongationFactory(
            declared_by_siae=job_app.to_company,
            approval=job_app.approval,
        )
        assert job_app in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        # ...and with an employee record already existing for that employee
        EmployeeRecordFactory(
            status=Status.READY,
            job_application__to_company=job_app.to_company,
            approval_number=job_app.approval.number,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

    def test_eligible_job_applications_with_a_suspended_or_extended_approval_older_than_cutoff(self):
        job_app = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=None,
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)
        SuspensionFactory(
            siae=job_app.to_company,
            approval=job_app.approval,
            created_at=timezone.make_aware(datetime.datetime(2001, 1, 1)),
        )
        ProlongationFactory(
            declared_by_siae=job_app.to_company,
            approval=job_app.approval,
            created_at=timezone.make_aware(datetime.datetime(2001, 1, 1)),
        )
        assert job_app not in JobApplication.objects.eligible_as_employee_record(job_app.to_company)

    def test_with_accepted_at_for_created_from_pe_approval(self):
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            origin=Origin.PE_APPROVAL,
        )

        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at == job_application.created_at

    def test_with_accepted_at_for_accept_transition(self):
        job_application = JobApplicationSentByCompanyFactory()
        job_application.process()
        job_application.accept(user=job_application.sender)

        expected_created_at = JobApplicationTransitionLog.objects.filter(
            job_application=job_application,
            transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
        ).aggregate(timestamp=Max("timestamp"))["timestamp"]
        assert JobApplication.objects.with_accepted_at().first().accepted_at == expected_created_at

    def test_with_accepted_at_with_multiple_transitions(self):
        job_application = JobApplicationSentByCompanyFactory()
        job_application.process()
        job_application.accept(user=job_application.sender)
        assert job_application.approval.number == "XXXXX0000001"
        job_application.cancel(user=job_application.sender)
        job_application.accept(user=job_application.sender)
        assert job_application.approval.number == "XXXXX0000002"
        job_application.cancel(user=job_application.sender)
        assert list(CancelledApproval.objects.order_by("number").values_list("number", flat=True)) == [
            "XXXXX0000001",
            "XXXXX0000002",
        ]

        expected_created_at = JobApplicationTransitionLog.objects.filter(
            job_application=job_application,
            transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
        ).aggregate(timestamp=Max("timestamp"))["timestamp"]
        # We should not have more job applications
        assert JobApplication.objects.with_accepted_at().count() == JobApplication.objects.count()
        assert JobApplication.objects.with_accepted_at().first().accepted_at == expected_created_at

    def test_accept_without_sender(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        job_application.process()
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender"])
        employer = job_application.to_company.members.first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=employer)
        recipients = []
        for email in mail.outbox:
            [recipient] = email.to
            recipients.append(recipient)
        assert recipients == [job_application.job_seeker.email, employer.email]

    def test_with_accepted_at_default_value(self):
        job_application = JobApplicationSentByCompanyFactory()

        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.process()  # 1 transition but no accept
        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.refuse(job_application.sender)  # 2 transitions, still no accept
        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

    def test_with_accepted_at_for_accepted_with_no_transition(self):
        JobApplicationSentByCompanyFactory(state=JobApplicationState.ACCEPTED)
        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at == job_application.created_at

    def test_with_accepted_at_for_ai_stock(self):
        JobApplicationFactory(origin=Origin.AI_STOCK)

        job_application = JobApplication.objects.with_accepted_at().first()
        assert job_application.accepted_at.date() == job_application.hiring_start_at
        assert job_application.accepted_at != job_application.created_at


class JobApplicationNotificationsTest(TestCase):
    AFPA = "Afpa"

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)

    def test_new_for_company(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            selected_jobs=Appellation.objects.all(),
        )
        employer = job_application.to_company.members.first()
        email = job_application.notifications_new_for_employer(employer).build()
        # To.
        assert employer.email in email.to
        assert len(email.to) == 1

        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.upper() in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.sender.get_full_name() in email.body
        assert job_application.sender.email in email.body
        assert format_filters.format_phone(job_application.sender.phone) in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.to_company.city in email.body
        assert str(job_application.to_company.pk) in email.body
        assert job_application.resume_link in email.body

    def test_new_for_prescriber(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, selected_jobs=Appellation.objects.all()
        )
        email = job_application.notifications_new_for_proxy.build()
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        assert job_application.sender_kind == SenderKind.PRESCRIBER

        # Subject
        assert job_application.job_seeker.get_full_name() in email.subject

        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.upper() in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.sender.get_full_name() in email.body
        assert job_application.sender.email in email.body
        assert format_filters.format_phone(job_application.sender.phone) in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.to_company.kind in email.body
        assert job_application.to_company.city in email.body

        # Assert the Job Seeker does not have access to confidential information.
        email = job_application.notifications_new_for_job_seeker.build()
        assert job_application.sender.get_full_name() in email.body
        assert job_application.sender_prescriber_organization.display_name in email.body
        assert job_application.sender.email not in email.body
        assert format_filters.format_phone(job_application.sender.phone) not in email.body
        assert job_application.resume_link in email.body

    def test_new_for_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory(selected_jobs=Appellation.objects.all())
        email = job_application.notifications_new_for_job_seeker.build()
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        assert job_application.sender_kind == SenderKind.JOB_SEEKER

        # Subject
        assert job_application.to_company.display_name in email.subject

        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.upper() in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.job_seeker.email in email.body
        assert format_filters.format_phone(job_application.job_seeker.phone) in email.body
        assert job_application.message in email.body
        for job in job_application.selected_jobs.all():
            assert job.display_name in email.body
        assert job_application.to_company.display_name in email.body
        assert reverse("login:job_seeker") in email.body
        assert reverse("account_reset_password") in email.body
        assert job_application.resume_link in email.body

    def test_accept_for_job_seeker(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        email = job_application.notifications_accept_for_job_seeker.build()
        # To.
        assert job_application.job_seeker.email == job_application.sender.email
        assert job_application.job_seeker.email in email.to
        assert len(email.to) == 1
        assert len(email.bcc) == 0
        # Subject.
        assert "Candidature acceptée" in email.subject
        # Body.
        assert job_application.to_company.display_name in email.body
        assert job_application.answer in email.body

    def test_accept_for_proxy(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        email = job_application.notifications_accept_for_proxy.build()
        # To.
        assert job_application.to_company.email not in email.to
        assert email.to == [job_application.sender.email]
        assert len(email.to) == 1
        assert len(email.bcc) == 0
        # Subject.
        assert "Candidature acceptée et votre avis sur les emplois de l'inclusion" in email.subject
        # Body.
        assert job_application.job_seeker.get_full_name() in email.body
        assert job_application.sender.get_full_name() in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.answer in email.body
        assert "Date de début du contrat" in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert "Date de fin du contrat" in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert job_application.sender_prescriber_organization.accept_survey_url in email.body

    def test_accept_for_proxy_without_hiring_end_at(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, hiring_end_at=None)
        email = job_application.notifications_accept_for_proxy.build()
        assert "Date de fin du contrat : Non renseigné" in email.body

    def test_accept_trigger_manual_approval(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=datetime.date.today(),
        )
        accepted_by = job_application.to_company.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        # To.
        assert settings.ITOU_EMAIL_CONTACT in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.job_seeker.first_name.title() in email.body
        assert job_application.job_seeker.last_name.upper() in email.body
        assert job_application.job_seeker.email in email.body
        assert job_application.job_seeker.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.to_company.siret in email.body
        assert job_application.to_company.kind in email.body
        assert job_application.to_company.get_kind_display() in email.body
        assert job_application.to_company.get_department_display() in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert accepted_by.get_full_name() in email.body
        assert accepted_by.email in email.body
        assert reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk]) in email.body

    def test_accept_trigger_manual_approval_without_hiring_end_at(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=datetime.date.today(),
            hiring_end_at=None,
        )
        accepted_by = job_application.to_company.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        assert "Date de fin du contrat : Non renseigné" in email.body

    def test_refuse(self):
        # When sent by authorized prescriber.
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.notifications_refuse_for_proxy.build()
        # To.
        assert job_application.sender.email in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.sender.get_full_name() in email.body
        assert job_application.job_seeker.get_full_name() in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.answer in email.body
        assert job_application.answer_to_prescriber in email.body
        assert self.AFPA not in email.body

        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.notifications_refuse_for_job_seeker.build()
        # To.
        assert job_application.job_seeker.email == job_application.sender.email
        assert job_application.job_seeker.email in email.to
        assert len(email.to) == 1
        # Body.
        assert job_application.to_company.display_name in email.body
        assert job_application.answer in email.body
        assert job_application.answer_to_prescriber not in email.body
        assert self.AFPA not in email.body

    def test_refuse_without_sender(self):
        # When sent by authorized prescriber.
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        job_application.process()
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender"])
        with self.captureOnCommitCallbacks(execute=True):
            job_application.refuse()
        [email] = mail.outbox
        assert email.to == [job_application.job_seeker.email]
        assert self.AFPA not in email.body

    def test_refuse_afpa_message(self):
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker__jobseeker_profile__hexa_post_code="59284",
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        email = job_application.notifications_refuse_for_job_seeker.build()
        assert [job_application.job_seeker.email] == email.to
        assert job_application.to_company.display_name in email.body
        assert job_application.answer in email.body
        assert job_application.answer_to_prescriber not in email.body
        assert self.AFPA in email.body

    def test_notifications_deliver_approval(self):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
        )
        accepted_by = job_application.to_company.members.first()
        email = job_application.notifications_deliver_approval(accepted_by).build()
        # To.
        assert accepted_by.email in email.to
        assert len(email.to) == 1
        # Body.
        assert approval.user.get_full_name() in email.subject
        assert approval.number_with_spaces in email.body
        assert approval.start_at.strftime("%d/%m/%Y") in email.body
        assert f"{approval.remainder.days} jours" in email.body
        assert approval.user.last_name.upper() in email.body
        assert approval.user.first_name.title() in email.body
        assert approval.user.birthdate.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_start_at.strftime("%d/%m/%Y") in email.body
        assert job_application.hiring_end_at.strftime("%d/%m/%Y") in email.body
        assert job_application.to_company.display_name in email.body
        assert job_application.to_company.get_kind_display() in email.body
        assert job_application.to_company.address_line_1 in email.body
        assert job_application.to_company.address_line_2 in email.body
        assert job_application.to_company.post_code in email.body
        assert job_application.to_company.city in email.body
        assert global_constants.ITOU_HELP_CENTER_URL in email.body
        assert job_application.to_company.accept_survey_url in email.body

    def test_notifications_deliver_approval_without_hiring_end_at(self):
        job_seeker = JobSeekerFactory()
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationState.ACCEPTED,
            approval=approval,
            hiring_end_at=None,
        )
        accepted_by = job_application.to_company.members.first()
        email = job_application.notifications_deliver_approval(accepted_by).build()
        assert "Se terminant le : Non renseigné" in email.body

    def test_notifications_deliver_approval_when_subject_to_eligibility_rules(self):
        job_application = JobApplicationFactory(with_approval=True, to_company__subject_to_eligibility=True)

        email = job_application.notifications_deliver_approval(job_application.to_company.members.first()).build()

        assert (
            f"PASS IAE pour {job_application.job_seeker.get_full_name()} et avis sur les emplois de l'inclusion"
            == email.subject
        )
        assert "PASS IAE" in email.body

    def test_notifications_deliver_approval_when_not_subject_to_eligibility_rules(self):
        job_application = JobApplicationFactory(with_approval=True, to_company__not_subject_to_eligibility=True)

        email = job_application.notifications_deliver_approval(job_application.to_company.members.first()).build()

        assert "Confirmation de l'embauche" == email.subject
        assert "PASS IAE" not in email.body
        assert global_constants.ITOU_HELP_CENTER_URL in email.body

    def test_manually_deliver_approval(self, *args, **kwargs):
        staff_member = ItouStaffFactory()
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval=approval,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_company.members.first())
        with self.captureOnCommitCallbacks(execute=True):
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
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
        )
        job_application.accept(user=job_application.to_company.members.first())
        with self.captureOnCommitCallbacks(execute=True):
            job_application.manually_refuse_approval(refused_by=staff_member)
        assert job_application.approval_manually_refused_by == staff_member
        assert job_application.approval_manually_refused_at is not None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_manually_delivered_by is None
        assert job_application.approval_number_sent_at is None
        assert len(mail.outbox) == 1

    def test_cancel_sent_by_prescriber(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationState.ACCEPTED
        )

        cancellation_user = job_application.to_company.active_members.first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        assert len(mail.outbox) == 2

        # To.
        assert [cancellation_user.email] == mail.outbox[0].to
        assert [job_application.sender.email] == mail.outbox[1].to

        # Body.
        assert "annulée" in mail.outbox[0].body
        assert job_application.sender.get_full_name() in mail.outbox[0].body
        assert job_application.job_seeker.get_full_name() in mail.outbox[0].body
        assert mail.outbox[0].body == mail.outbox[1].body

    def test_cancel_sent_by_job_seeker(self):
        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationState.ACCEPTED)

        cancellation_user = job_application.to_company.active_members.first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        assert len(mail.outbox) == 1

        # To.
        assert [cancellation_user.email] == mail.outbox[0].to

        # Body.
        assert "annulée" in mail.outbox[0].body
        assert job_application.sender.get_full_name() in mail.outbox[0].body
        assert job_application.job_seeker.get_full_name() in mail.outbox[0].body

    def test_cancel_without_sender(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationState.ACCEPTED
        )
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender"])
        cancellation_user = job_application.to_company.active_members.first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        [email] = mail.outbox
        assert email.to == [cancellation_user.email]


@override_settings(
    API_ESD={
        "BASE_URL": "https://base.domain",
        "AUTH_BASE_URL": "https://authentication-domain.fr",
        "KEY": "foobar",
        "SECRET": "pe-secret",
    }
)
class JobApplicationWorkflowTest(TestCase):
    SENT_PASS_EMAIL_SUBJECT = "PASS IAE pour"
    ACCEPT_EMAIL_SUBJECT_PROXY = "Candidature acceptée et votre avis sur les emplois de l'inclusion"
    ACCEPT_EMAIL_SUBJECT_JOB_SEEKER = "Candidature acceptée"

    def test_accept_job_application_sent_by_job_seeker_and_make_others_obsolete(self):
        """
        When a job seeker's application is accepted, the others are marked obsolete.
        """
        job_seeker = JobSeekerFactory(with_pole_emploi_id=True)
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_seeker.jobseeker_profile.pole_emploi_id != ""

        kwargs = {
            "job_seeker": job_seeker,
            "sender": job_seeker,
            "sender_kind": SenderKind.JOB_SEEKER,
        }
        JobApplicationFactory(state=JobApplicationState.NEW, **kwargs)
        JobApplicationFactory(state=JobApplicationState.PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationState.POSTPONED, **kwargs)
        JobApplicationFactory(state=JobApplicationState.PROCESSING, **kwargs)

        assert job_seeker.job_applications.count() == 4
        assert job_seeker.job_applications.pending().count() == 4

        job_application = job_seeker.job_applications.filter(state=JobApplicationState.PROCESSING).first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationState.ACCEPTED).count() == 1
        assert job_seeker.job_applications.filter(state=JobApplicationState.OBSOLETE).count() == 3

        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[1].subject

    def test_accept_obsolete(self):
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
            JobApplicationState.NEW,
            JobApplicationState.PROCESSING,
            JobApplicationState.POSTPONED,
            JobApplicationState.ACCEPTED,
            JobApplicationState.OBSOLETE,
            JobApplicationState.OBSOLETE,
        ]:
            JobApplicationFactory(state=state, **kwargs)

        assert job_seeker.job_applications.count() == 6

        job_application = job_seeker.job_applications.filter(state=JobApplicationState.OBSOLETE).first()
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationState.ACCEPTED).count() == 2
        assert job_seeker.job_applications.filter(state=JobApplicationState.OBSOLETE).count() == 4

        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval(self):
        """
        When a Pôle emploi approval already exists, it is reused.
        """
        job_seeker = JobSeekerFactory(with_pole_emploi_id=True)
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.jobseeker_profile.pole_emploi_id, birthdate=job_seeker.birthdate
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationState.PROCESSING
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval.number == pe_approval.number
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin == Origin.PE_APPROVAL
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == job_application.sender_kind
        assert job_application.approval.origin_prescriber_organization_kind == ""
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval_with_nir(self):
        job_seeker = JobSeekerFactory(jobseeker_profile__pole_emploi_id="", birthdate=None)
        pe_approval = PoleEmploiApprovalFactory(nir=job_seeker.jobseeker_profile.nir)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationState.PROCESSING
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval.number == pe_approval.number
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin == Origin.PE_APPROVAL
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == job_application.sender_kind
        assert job_application.approval.origin_prescriber_organization_kind == ""
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_forgotten_pole_emploi_id(self):
        """
        When a Pôle emploi ID is forgotten, a manual approval delivery is triggered.
        """
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationState.PROCESSING
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_MANUAL
        # Check sent email.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the team.
        assert "PASS IAE requis sur Itou" in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_a_nir_no_pe_approval(self):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == job_application.sender_kind
        assert job_application.approval.origin_prescriber_organization_kind == ""
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_a_pole_emploi_id_no_pe_approval(self):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            with_pole_emploi_id=True,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_unregistered_no_pe_approval(self):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert job_application.approval.origin_prescriber_organization_kind == ""
        assert len(mail.outbox) == 2
        assert "Candidature acceptée" in mail.outbox[0].subject
        assert "PASS IAE pour " in mail.outbox[1].subject

    def test_accept_job_application_sent_by_prescriber(self):
        """
        Accept a job application sent by an "orienteur".
        """
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker__with_pole_emploi_id=True,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id != ""
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.PRESCRIBER
        assert (
            job_application.approval.origin_prescriber_organization_kind
            == job_application.sender_prescriber_organization.kind
        )
        # Check sent email.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[2].subject

    def test_accept_job_application_sent_by_authorized_prescriber(self):
        """
        Accept a job application sent by an authorized prescriber.
        """
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
            job_seeker__with_pole_emploi_id=True,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id != ""
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.PRESCRIBER
        assert (
            job_application.approval.origin_prescriber_organization_kind
            == job_application.sender_prescriber_organization.kind
        )
        # Check sent email.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[2].subject

    def test_accept_job_application_sent_by_authorized_prescriber_with_approval_in_waiting_period(self):
        """
        An authorized prescriber can bypass the waiting period.
        """
        user = JobSeekerFactory(with_pole_emploi_id=True)
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        assert approval.is_in_waiting_period
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            job_seeker=user,
            state=JobApplicationState.PROCESSING,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id != ""
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.PRESCRIBER
        assert (
            job_application.approval.origin_prescriber_organization_kind
            == job_application.sender_prescriber_organization.kind
        )
        # Check sent emails.
        assert len(mail.outbox) == 3
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mail.outbox[1].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[2].subject

    def test_accept_job_application_sent_by_prescriber_with_approval_in_waiting_period(self):
        """
        An "orienteur" cannot bypass the waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        assert approval.is_in_waiting_period
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=user,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=None,
        )
        with pytest.raises(xwf_models.AbortTransition):
            job_application.accept(user=job_application.to_company.members.first())

    def test_accept_job_application_sent_by_job_seeker_in_waiting_period_valid_diagnosis(self):
        """
        A job seeker with a valid diagnosis can start an IAE path
        even if he's in a waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        assert approval.is_in_waiting_period

        diagnosis = EligibilityDiagnosisFactory(job_seeker=user)
        assert diagnosis.is_valid

        job_application = JobApplicationSentByJobSeekerFactory(job_seeker=user, state=JobApplicationState.PROCESSING)
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert job_application.approval.origin_prescriber_organization_kind == ""
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mail.outbox[1].subject

    def test_accept_job_application_by_siae_with_no_approval(self):
        """
        A SIAE can hire somebody without getting approval if they don't want one
        Basically the same as the 'accept' part, except we don't create an approval
        and we don't notify
        """
        job_application = JobApplicationWithoutApprovalFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker__with_pole_emploi_id=True,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id != ""
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.approval is None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == ""
        # Check sent email (no notification of approval).
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mail.outbox[1].subject

    def test_accept_job_application_by_siae_not_subject_to_eligibility_rules(self):
        """
        No approval should be delivered for an employer not subject to eligibility rules.
        """
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
        )
        with self.captureOnCommitCallbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert not job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.approval is None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == ""
        # Check sent emails.
        assert len(mail.outbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mail.outbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mail.outbox[1].subject

    def test_accept_has_link_to_eligibility_diagnosis(self):
        """
        Given a job application for an SIAE subject to eligibility rules,
        when accepting it, then the eligibility diagnosis is linked to it.
        """
        job_application = JobApplicationSentByCompanyFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.EI,
            eligibility_diagnosis=None,
            job_seeker__with_pole_emploi_id=True,
        )

        to_company = job_application.to_company
        to_employer_member = to_company.members.first()
        job_seeker = job_application.job_seeker

        eligibility_diagnosis = EligibilityDiagnosisMadeBySiaeFactory(
            job_seeker=job_seeker, author=to_employer_member, author_siae=to_company
        )

        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_seeker.jobseeker_profile.pole_emploi_id != ""

        job_application.accept(user=to_employer_member)
        assert job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.eligibility_diagnosis == eligibility_diagnosis

    def test_refuse(self):
        user = JobSeekerFactory()
        kwargs = {"job_seeker": user, "sender": user, "sender_kind": SenderKind.JOB_SEEKER}

        JobApplicationFactory(state=JobApplicationState.PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationState.POSTPONED, **kwargs)

        assert user.job_applications.count() == 2
        assert user.job_applications.pending().count() == 2

        for job_application in user.job_applications.all():
            with self.captureOnCommitCallbacks(execute=True):
                job_application.refuse()
            # Check sent email.
            assert len(mail.outbox) == 1
            assert "Candidature déclinée" in mail.outbox[0].subject
            mail.outbox = []

    def test_cancel_delete_linked_approval(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)
        assert job_application.job_seeker.approvals.count() == 1
        assert JobApplication.objects.filter(approval=job_application.approval).count() == 1

        cancellation_user = job_application.to_company.active_members.first()
        job_application.cancel(user=cancellation_user)

        assert job_application.state == JobApplicationState.CANCELLED

        job_application.refresh_from_db()
        assert not job_application.approval

    def test_cancel_do_not_delete_linked_approval(self, *args, **kwargs):
        # The approval is linked to two accepted job applications
        job_application = JobApplicationFactory(with_approval=True)
        approval = job_application.approval
        JobApplicationFactory(with_approval=True, approval=approval, job_seeker=job_application.job_seeker)

        assert job_application.job_seeker.approvals.count() == 1
        assert JobApplication.objects.filter(approval=approval).count() == 2

        cancellation_user = job_application.to_company.active_members.first()
        job_application.cancel(user=cancellation_user)

        assert job_application.state == JobApplicationState.CANCELLED

        job_application.refresh_from_db()
        assert job_application.approval

    def test_cancellation_not_allowed(self, *args, **kwargs):
        today = datetime.date.today()

        # Linked employee record with blocking status
        job_application = JobApplicationFactory(with_approval=True, hiring_start_at=(today - relativedelta(days=365)))
        cancellation_user = job_application.to_company.active_members.first()
        EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED)

        # xworkflows.base.AbortTransition
        with pytest.raises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)

        # Wrong state
        job_application = JobApplicationFactory(
            with_approval=True, hiring_start_at=today, state=JobApplicationState.NEW
        )
        cancellation_user = job_application.to_company.active_members.first()
        with pytest.raises(xwf_models.AbortTransition):
            job_application.cancel(user=cancellation_user)


class JobApplicationXlsxExportTest(TestCase):
    def test_xlsx_export_contains_the_necessary_info(self, *args, **kwargs):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_seeker = JobSeekerFactory(title=Title.MME)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            selected_jobs=Appellation.objects.all(),
            eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_company.members.first())

        # The accept transition above will create a valid PASS IAE for the job seeker.
        assert job_seeker.approvals.last().is_valid

        response = stream_xlsx_export(JobApplication.objects.all(), "filename")
        assert get_rows_from_streaming_response(response) == [
            JOB_APPLICATION_CSV_HEADERS,
            [
                "MME",
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                job_seeker.birthdate.strftime("%d/%m/%Y"),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
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
                "Valide",
            ],
        ]

    def test_display_expired_approvals_info(self):
        """Even expired approval should be displayed."""
        with freeze_time(timezone.now() - relativedelta(days=Approval.DEFAULT_APPROVAL_DAYS + 2)):
            create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
            job_seeker = JobSeekerFactory(title=Title.MME)
            job_application = JobApplicationSentByJobSeekerFactory(
                job_seeker=job_seeker,
                state=JobApplicationState.PROCESSING,
                selected_jobs=Appellation.objects.all(),
                eligibility_diagnosis=EligibilityDiagnosisFactory(job_seeker=job_seeker),
            )
            job_application.accept(user=job_application.to_company.members.first())

        assert job_seeker.approvals.last().is_in_waiting_period

        response = stream_xlsx_export(JobApplication.objects.all(), "filename")
        assert get_rows_from_streaming_response(response) == [
            JOB_APPLICATION_CSV_HEADERS,
            [
                "MME",
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                job_seeker.birthdate.strftime("%d/%m/%Y"),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                job_application.created_at.strftime("%d/%m/%Y"),
                "Candidature acceptée",
                job_application.hiring_start_at.strftime("%d/%m/%Y"),
                job_application.hiring_end_at.strftime("%d/%m/%Y"),
                "",  # no reafusal reason
                "non",  # Eligibility status.
                job_application.approval.number,
                job_application.approval.start_at.strftime("%d/%m/%Y"),
                job_application.approval.end_at.strftime("%d/%m/%Y"),
                "Expiré",
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

        job_application = JobApplicationFactory(state=JobApplicationState.PROCESSING, **kwargs)
        job_application.refuse()

        response = stream_xlsx_export(JobApplication.objects.all(), "filename")
        assert get_rows_from_streaming_response(response) == [
            JOB_APPLICATION_CSV_HEADERS,
            [
                job_seeker.title,
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                job_seeker.birthdate.strftime("%d/%m/%Y"),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
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
                "",
            ],
        ]

    def test_all_gender_cases_in_export(self):
        assert _resolve_title(title="", nir="") == ""
        assert _resolve_title(title=Title.M, nir="") == Title.M
        assert _resolve_title(title="", nir="1") == Title.M
        assert _resolve_title(title="", nir="2") == Title.MME
        with pytest.raises(KeyError):
            _resolve_title(title="", nir="0")


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
            "sender_company",
            "sender_prescriber_organization",
            "to_company",
            "state",
            "selected_jobs",
            "hired_job",
            "message",
            "answer",
            "answer_to_prescriber",
            "refusal_reason",
            "refusal_reason_shared_with_job_seeker",
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
            "hidden_for_company",
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
            "inverted_vae_contract",
        ]
        form = JobApplicationAdminForm()
        assert list(form.fields.keys()) == form_fields_list

        # mandatory fields : job_seeker, to_company
        form_errors = {
            "job_seeker": [{"message": "Ce champ est obligatoire.", "code": "required"}],
            "to_company": [{"message": "Ce champ est obligatoire.", "code": "required"}],
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
        sender_company = job_application.sender_company

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

        job_application.sender_company = JobApplicationSentByCompanyFactory().sender_company
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_company = sender_company

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
        job_application = JobApplicationSentByCompanyFactory()
        sender_company = job_application.sender_company
        sender = job_application.sender

        job_application.sender_company = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice manquante."] == form.errors["__all__"]
        job_application.sender_company = sender_company

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

        job_application.sender_company = JobApplicationSentByCompanyFactory().sender_company
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice inattendue."] == form.errors["__all__"]
        job_application.sender_company = None

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
