import datetime
import json
import random

import factory.fuzzy
import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Max
from django.forms.models import model_to_dict
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries, assertQuerySetEqual

from itou.approvals.models import Approval, CancelledApproval
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordTransition, EmployeeRecordTransitionLog
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.admin_forms import JobApplicationAdminForm
from itou.job_applications.enums import (
    ARCHIVABLE_JOB_APPLICATION_STATES,
    AUTO_REJECT_JOB_APPLICATION_DELAY,
    AUTO_REJECT_JOB_APPLICATION_STATES,
    JobApplicationState,
    Origin,
    QualificationLevel,
    QualificationType,
    RefusalReason,
    SenderKind,
)
from itou.job_applications.export import JOB_APPLICATION_XSLX_FORMAT, _resolve_title, stream_xlsx_export
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.users.enums import LackOfPoleEmploiId, Title, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.templatetags import format_filters
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
)
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.employee_record.factories import BareEmployeeRecordFactory, EmployeeRecordFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationWithApprovalNotCancellableFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import excel_date_format, get_rows_from_streaming_response


class TestJobApplicationModel:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.API_ESD = {
            "BASE_URL": "https://base.domain",
            "AUTH_BASE_URL": "https://authentication-domain.fr",
            "KEY": "foobar",
            "SECRET": "pe-secret",
        }

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
        assert not job_application.eligibility_diagnosis_by_siae_required()

        job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.EI,
            eligibility_diagnosis=None,
        )
        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        assert not has_considered_valid_diagnoses
        assert job_application.eligibility_diagnosis_by_siae_required()

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

    def test_refused_by_without_user(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
        )
        job_application.refuse(user=None)
        assert job_application.refused_by is None

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

    def test_is_refused_for_other_reason(self, subtests):
        job_application = JobApplicationFactory()
        for state in JobApplicationState.values:
            for refusal_reason in RefusalReason.values:
                with subtests.test(
                    "Test state and refusal_reason permutations", state=state, refusal_reason=refusal_reason
                ):
                    job_application.state = state
                    job_application.refusal_reason = refusal_reason

                    if state == JobApplicationState.REFUSED and refusal_reason == RefusalReason.OTHER:
                        assert job_application.is_refused_for_other_reason
                    else:
                        assert not job_application.is_refused_for_other_reason

    def test_get_sender_kind_display(self, subtests):
        non_siae_items = [
            (JobApplicationSentByCompanyFactory(to_company__kind=kind), "Employeur")
            for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.GEIQ, CompanyKind.OPCS]
        ]
        items = [
            [JobApplicationFactory(sent_by_authorized_prescriber_organisation=True), "Prescripteur"],
            [JobApplicationSentByPrescriberOrganizationFactory(), "Orienteur"],
            [JobApplicationSentByCompanyFactory(), "Employeur"],
            [JobApplicationSentByJobSeekerFactory(), "Demandeur d'emploi"],
        ] + non_siae_items

        for job_application, sender_kind_display in items:
            with subtests.test(sender_kind_display):
                assert job_application.get_sender_kind_display() == sender_kind_display

    def test_application_on_non_job_seeker(self):
        with pytest.raises(ValidationError) as excinfo:
            JobApplicationFactory(job_seeker=PrescriberFactory()).clean()
        assert "Impossible de candidater pour cet utilisateur, celui-ci n'est pas un compte candidat" in str(
            excinfo.value
        )

    def test_inverted_vae_contract(self):
        JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, inverted_vae_contract=True).clean()
        JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, inverted_vae_contract=False).clean()
        JobApplicationFactory(to_company__kind=CompanyKind.EI, inverted_vae_contract=None).clean()
        with pytest.raises(ValidationError) as excinfo:
            JobApplicationFactory(to_company__kind=CompanyKind.AI, inverted_vae_contract=True).clean()
        assert "Un contrat associé à une VAE inversée n'est possible que pour les GEIQ" in str(excinfo.value)

    def test_accept_follow_up_group(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
        )
        user = job_application.to_company.members.first()
        assert not FollowUpGroup.objects.exists()

        job_application.accept(user=user)
        group = FollowUpGroup.objects.get()
        assert group.beneficiary == job_application.job_seeker
        membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
        assert membership.member == user
        assert membership.creator == user


@pytest.mark.parametrize(
    "factory,constraint_name",
    [
        pytest.param(
            lambda: JobApplicationSentByJobSeekerFactory(sender=JobSeekerFactory()),
            "job_seeker_sender_coherence",
            id="sent_by_other_job_seeker",
        ),
        pytest.param(
            lambda: JobApplicationSentByCompanyFactory(sender_company=None),
            "employer_sender_coherence",
            id="sent_by_employer_without_company",
        ),
        pytest.param(
            lambda: JobApplicationSentByCompanyFactory(sender_prescriber_organization=PrescriberOrganizationFactory()),
            "employer_sender_coherence",
            id="sent_by_employer_with_prescriber_organization",
        ),
        pytest.param(
            lambda: JobApplicationSentByCompanyFactory(
                sender_company=None, sender_prescriber_organization=PrescriberOrganizationFactory()
            ),
            "employer_sender_coherence",
            id="sent_by_employer_without_company_and_with_prescriber_organization",
        ),
        pytest.param(
            lambda: JobApplicationSentByPrescriberFactory(sender_company=CompanyFactory()),
            "prescriber_sender_coherence",
            id="sent_by_employer_with_company",
        ),
    ],
)
def test_sender_constraints(factory, constraint_name):
    with pytest.raises(
        IntegrityError, match=f'new row for relation ".*" violates check constraint "{constraint_name}"'
    ):
        factory()


@pytest.mark.parametrize(
    "job_application_factory",
    [
        JobApplicationSentByCompanyFactory,
        JobApplicationSentByPrescriberFactory,
        JobApplicationSentByJobSeekerFactory,
    ],
)
def test_sender_kind_of_job_application(job_application_factory):
    # sender_kind is equal to the sender's kind
    job_application = job_application_factory()
    job_application.clean()

    # sender_kind is different from the sender's kind
    job_application.sender_kind = random.choice([kind for kind in UserKind if kind != job_application.sender.kind])
    with pytest.raises(ValidationError):
        job_application.clean()

    # sender_kind and sender are None
    job_application.sender_kind = None
    job_application.sender = None
    job_application.clean()


def test_can_be_cancelled():
    assert JobApplicationFactory().can_be_cancelled is True


def test_can_be_cancelled_when_origin_is_ai_stock():
    assert JobApplicationFactory(origin=Origin.AI_STOCK).can_be_cancelled is False


def test_can_be_cancelled_when_an_employee_record_without_logs_exists():
    employee_record = BareEmployeeRecordFactory(
        job_application=JobApplicationFactory(),
        status=factory.fuzzy.FuzzyChoice(Status),
    )
    assert employee_record.job_application.can_be_cancelled is True


@pytest.mark.parametrize("transition", EmployeeRecordTransition.without_asp_exchange())
def test_can_be_cancelled_when_an_employee_record_with_non_blocking_logs_exists(transition):
    employee_record = BareEmployeeRecordFactory(
        job_application=JobApplicationFactory(),
        status=factory.fuzzy.FuzzyChoice(Status),
    )

    EmployeeRecordTransitionLog.log_transition(
        transition=transition,
        from_state=factory.fuzzy.FuzzyChoice(Status),
        to_state=factory.fuzzy.FuzzyChoice(Status),
        modified_object=employee_record,
    )
    assert employee_record.job_application.can_be_cancelled is True


@pytest.mark.parametrize("transition", set(Status) - EmployeeRecordTransition.without_asp_exchange())
def test_can_be_cancelled_when_an_employee_record_with_blocking_logs_exists(transition):
    employee_record = BareEmployeeRecordFactory(
        job_application=JobApplicationFactory(),
        status=factory.fuzzy.FuzzyChoice(Status),
    )

    EmployeeRecordTransitionLog.log_transition(
        transition=transition,
        from_state=factory.fuzzy.FuzzyChoice(Status),
        to_state=factory.fuzzy.FuzzyChoice(Status),
        modified_object=employee_record,
    )
    assert employee_record.job_application.can_be_cancelled is False


def test_diagnoses_coherence_contraint():
    job_application = JobApplicationFactory(with_geiq_eligibility_diagnosis=True)
    job_application.eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

    # Mind the parens in RE...
    with pytest.raises(
        ValidationError, match="Une candidature ne peut avoir les deux types de diagnostics \\(IAE et GEIQ\\)"
    ):
        job_application.validate_constraints()


@pytest.mark.parametrize(
    "data,error",
    [
        ({"nb_hours_per_week": 20}, "Le nombre d'heures par semaine ne peut être saisi que pour un GEIQ"),
        (
            {"contract_type_details": "foo"},
            "Les précisions sur le type de contrat ne peuvent être saisies que pour un GEIQ",
        ),
        ({"contract_type": ContractType.OTHER}, "Le type de contrat ne peut être saisi que pour un GEIQ"),
    ],
    ids=repr,
)
def test_geiq_fields_validation_error(data, error):
    job_application = JobApplicationFactory(to_company__kind=CompanyKind.EI)
    for name, value in data.items():
        setattr(job_application, name, value)

    with pytest.raises(ValidationError, match=error):
        job_application.clean()


@pytest.mark.parametrize(
    "data",
    [
        {"contract_type": ContractType.APPRENTICESHIP, "nb_hours_per_week": 35},
        {"contract_type": ContractType.PROFESSIONAL_TRAINING, "nb_hours_per_week": 35},
        {"contract_type": ContractType.OTHER, "nb_hours_per_week": 30, "contract_type_details": "foo"},
    ],
    ids=repr,
)
def test_geiq_fields_validation_success(data):
    JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, **data)


@pytest.mark.parametrize(
    "data",
    [
        {"contract_type": ContractType.PROFESSIONAL_TRAINING, "contract_type_details": "foo"},
        {"contract_type": ContractType.OTHER},
        {"contract_type_details": "foo"},
        {"nb_hours_per_week": 1},
        {"nb_hours_per_week": 1, "contract_type_details": "foo"},
        {"nb_hours_per_week": 1, "contract_type": ContractType.OTHER},
    ],
    ids=repr,
)
def test_geiq_contract_fields_contraint(data):
    job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
    for name, value in data.items():
        setattr(job_application, name, value)

    with pytest.raises(ValidationError, match="Incohérence dans les champs concernant le contrat GEIQ"):
        job_application.validate_constraints()


def test_geiq_qualification_fields_contraint():
    with pytest.raises(
        Exception, match="Incohérence dans les champs concernant la qualification pour le contrat GEIQ"
    ):
        JobApplicationFactory.build(
            to_company__kind=CompanyKind.GEIQ,
            qualification_type=QualificationType.STATE_DIPLOMA,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        ).validate_constraints()

    for qualification_type in [QualificationType.CQP, QualificationType.CCN]:
        JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            qualification_type=qualification_type,
            qualification_level=QualificationLevel.NOT_RELEVANT,
        )


def test_can_have_prior_action():
    geiq = CompanyFactory.build(kind=CompanyKind.GEIQ)
    non_geiq = CompanyFactory.build(kind=CompanyKind.AI)

    assert JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.NEW).can_have_prior_action is True
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

    assert JobApplicationFactory.build(to_company=geiq, state=JobApplicationState.NEW).can_change_prior_actions is True
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


def test_prescriptions_of_for_employer_with_company():
    job_application = JobApplicationFactory(sent_by_another_employer=True)
    assert list(JobApplication.objects.prescriptions_of(job_application.sender, job_application.sender_company)) == [
        job_application
    ]


def test_prescriptions_of_for_employer_without_company():
    job_application = JobApplicationFactory(sent_by_company=True)
    assert list(JobApplication.objects.prescriptions_of(job_application.sender, job_application.sender_company)) == []
    assert list(JobApplication.objects.prescriptions_of(job_application.sender, job_application.to_company)) == []


def test_prescriptions_of_for_employer_is_based_on_company():
    job_application = JobApplicationFactory(sent_by_another_employer=True)
    dummy_employer = EmployerFactory.build()
    assert list(JobApplication.objects.prescriptions_of(dummy_employer, job_application.sender_company)) == [
        job_application
    ]
    assert list(JobApplication.objects.prescriptions_of(dummy_employer, job_application.to_company)) == []


def test_prescriptions_of_exclude_auto_prescription():
    job_application = JobApplicationSentByCompanyFactory()
    assert list(JobApplication.objects.prescriptions_of(job_application.sender, job_application.to_company)) == []


class TestJobApplicationQuerySet:
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

    def test_with_jobseeker_eligibility_diagnosis_with_a_denormalized_diagnosis_from_prescriber(self):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company__subject_to_eligibility=True,
            eligibility_diagnosis=None,
        )
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            from_prescriber=True,
            job_seeker=job_application.job_seeker,
        )

        qs = JobApplication.objects.with_jobseeker_eligibility_diagnosis()
        assert list(qs) == [job_application]
        assert qs.first().jobseeker_eligibility_diagnosis == eligibility_diagnosis.pk

    def test_with_jobseeker_eligibility_diagnosis_with_a_denormalized_diagnosis_from_current_employer(self):
        job_application = JobApplicationSentByCompanyFactory(
            to_company__subject_to_eligibility=True,
            eligibility_diagnosis=None,
        )
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            from_employer=True,
            author_siae=job_application.sender_company,
            job_seeker=job_application.job_seeker,
        )

        qs = JobApplication.objects.with_jobseeker_eligibility_diagnosis()
        assert list(qs) == [job_application]
        assert qs.first().jobseeker_eligibility_diagnosis == eligibility_diagnosis.pk

    def test_with_jobseeker_eligibility_diagnosis_with_a_denormalized_diagnosis_from_another_employer(self):
        job_application = JobApplicationSentByCompanyFactory(
            to_company__subject_to_eligibility=True,
            eligibility_diagnosis=None,
        )
        IAEEligibilityDiagnosisFactory(
            from_employer=True,
            job_seeker=job_application.job_seeker,
        )

        qs = JobApplication.objects.with_jobseeker_eligibility_diagnosis()
        assert list(qs) == [job_application]
        assert qs.first().jobseeker_eligibility_diagnosis is None

    def test_with_eligibility_diagnosis_criterion(self):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, created_at=timezone.now())
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

        older_diagnosis = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=job_app.job_seeker, created_at=timezone.now() - relativedelta(months=1)
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
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_app.job_seeker)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteriaLevel.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        criteria = [level1_criterion.pk, level2_criterion.pk, level1_other_criterion.pk]
        obj = JobApplication.objects.with_list_related_data(criteria).get(pk=job_app.pk)

        with assertNumQueries(0):
            # select / prefetch
            assert hasattr(obj, "approval")
            assert hasattr(obj, "job_seeker")
            assert hasattr(obj, "sender")
            assert hasattr(obj, "sender_company")
            assert hasattr(obj, "sender_prescriber_organization")
            assert hasattr(obj, "to_company")
            assert hasattr(obj, "selected_jobs")
            # annotations
            assert hasattr(obj, f"eligibility_diagnosis_criterion_{level1_criterion.pk}")
            assert hasattr(obj, f"eligibility_diagnosis_criterion_{level2_criterion.pk}")
            assert hasattr(obj, f"eligibility_diagnosis_criterion_{level1_other_criterion.pk}")
            assert hasattr(obj, "jobseeker_eligibility_diagnosis")

    def test_eligible_as_employee_record(self):
        # A valid job application:
        job_app = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        job_app_with_future_hiring_start_at = JobApplicationFactory(
            to_company=job_app.to_company,
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
            hiring_start_at=timezone.localdate() + datetime.timedelta(days=1),
        )
        assert set(JobApplication.objects.eligible_as_employee_record(job_app.to_company)) == {
            job_app,
            job_app_with_future_hiring_start_at,
        }

        # Test all disabling criteria
        # ----------------------------
        def assert_job_app_not_in_queryset(ja):
            assert ja not in JobApplication.objects.eligible_as_employee_record(ja.to_company)

        # Status is not accepted
        job_app_not_accepted = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            with_approval=True,
        )
        assert_job_app_not_in_queryset(job_app_not_accepted)

        # without an approval
        job_app_without_approval = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
        )
        assert_job_app_not_in_queryset(job_app_without_approval)

        # `create_employee_record` is False.
        job_app_blocked_creation = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
            create_employee_record=False,
        )
        assert_job_app_not_in_queryset(job_app_blocked_creation)

        # Already has an employee record
        job_app_with_employee_record = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            with_approval=True,
        )
        employee_record = EmployeeRecordFactory(
            job_application=job_app_with_employee_record,
            asp_id=job_app_with_employee_record.to_company.convention.asp_id,
            approval_number=job_app_with_employee_record.approval.number,
            status=Status.NEW,
        )
        assert_job_app_not_in_queryset(job_app_with_employee_record)
        # Even if it's disabled
        employee_record.disable()
        assert employee_record.status == Status.DISABLED
        assert_job_app_not_in_queryset(job_app_with_employee_record)

        # There's already an employee record for the same SIAE and the same approval (job_app)
        job_app_on_same_siae = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            to_company=job_app_with_employee_record.to_company,
            approval=job_app_with_employee_record.approval,
        )
        assert_job_app_not_in_queryset(job_app_on_same_siae)

        # There's already an employee record for a SIAE of the same convention and the same approval
        job_app_on_same_convention = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            to_company__convention=job_app_with_employee_record.to_company.convention,
            to_company__source=Company.SOURCE_USER_CREATED,
            approval=job_app_with_employee_record.approval,
        )
        assert_job_app_not_in_queryset(job_app_on_same_convention)

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

    def test_accept_without_sender(self, django_capture_on_commit_callbacks, mailoutbox):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        job_application.process()
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender", "updated_at"])
        employer = job_application.to_company.members.first()
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=employer)
        recipients = []
        for email in mailoutbox:
            [recipient] = email.to
            recipients.append(recipient)
        assert recipients == [employer.email, job_application.job_seeker.email]

    def test_with_accepted_at_default_value(self):
        job_application = JobApplicationSentByCompanyFactory()

        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.process()  # 1 transition but no accept
        assert JobApplication.objects.with_accepted_at().first().accepted_at is None

        job_application.refuse(user=job_application.sender)  # 2 transitions, still no accept
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

    def test_is_active_company_member(self):
        job_application = JobApplicationFactory()
        user = EmployerFactory()
        assert JobApplication.objects.is_active_company_member(user).count() == 0

        job_application.to_company.add_or_activate_membership(user)
        assert JobApplication.objects.is_active_company_member(user).get() == job_application

        membership = job_application.to_company.memberships.filter(user=user).get()
        membership.is_active = False
        membership.save(update_fields=("is_active", "updated_at"))

        assert JobApplication.objects.is_active_company_member(user).count() == 0

    @pytest.mark.parametrize(
        "state,expected",
        [(state, state in AUTO_REJECT_JOB_APPLICATION_STATES) for state in JobApplicationState],
    )
    def test_automatically_rejectable_applications(self, state, expected):
        old_job_application = JobApplicationFactory(
            state=state, updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY
        )
        if state in ARCHIVABLE_JOB_APPLICATION_STATES:
            JobApplicationFactory(
                state=state,
                updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY,
                archived_at=timezone.now(),
            )
        JobApplicationFactory(
            state=state, updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY + datetime.timedelta(days=1)
        )

        qs = JobApplication.objects.automatically_rejectable_applications()
        assert qs.exists() == expected
        if expected:
            assert set(qs) == {old_job_application}


class TestJobApplicationNotifications:
    @pytest.fixture(autouse=True)
    def setup_method(self):
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
        assert job_application.job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") in email.body
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
        assert job_application.job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") in email.body
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
        assert job_application.job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") in email.body
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
            hiring_start_at=timezone.localdate(),
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
        assert job_application.job_seeker.jobseeker_profile.birthdate.strftime("%d/%m/%Y") in email.body
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
            hiring_start_at=timezone.localdate(),
            hiring_end_at=None,
        )
        accepted_by = job_application.to_company.members.first()
        email = job_application.email_manual_approval_delivery_required_notification(accepted_by)
        assert "Date de fin du contrat : Non renseigné" in email.body

    @pytest.mark.parametrize("is_sent_by_proxy", [True, False])
    @pytest.mark.parametrize("is_shared_with_job_seeker", [True, False])
    def test_refuse(self, is_sent_by_proxy, is_shared_with_job_seeker, snapshot):
        extra_kwargs = {}
        if is_sent_by_proxy:
            extra_kwargs = {
                "sender_prescriber_organization__membership__user__for_snapshot": True,
                "answer_to_prescriber": "Le candidat n'est pas venu.",
            }

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=is_sent_by_proxy,
            refusal_reason_shared_with_job_seeker=is_shared_with_job_seeker,
            refusal_reason=RefusalReason.DID_NOT_COME_TO_INTERVIEW,
            answer="Pas venu",
            for_snapshot=True,
            **extra_kwargs,
        )

        # Notification content sent to job seeker.
        email = job_application.notifications_refuse_for_job_seeker.build()
        assert job_application.job_seeker.email in email.to
        assert len(email.to) == 1
        assert email.body == snapshot(name="job_seeker_email")

        if is_sent_by_proxy:
            # Notification content sent to authorized prescriber.
            email = job_application.notifications_refuse_for_proxy.build()
            assert job_application.sender.email in email.to
            assert len(email.to) == 1
            assert email.body == snapshot(name="prescriber_email")

    def test_refuse_without_sender(self, django_capture_on_commit_callbacks, mailoutbox):
        # When sent by authorized prescriber.
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            refusal_reason=RefusalReason.DID_NOT_COME,
            answer_to_prescriber="Le candidat n'est pas venu.",
        )
        job_application.process()
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender", "updated_at"])
        with django_capture_on_commit_callbacks(execute=True):
            job_application.refuse(user=job_application.to_company.members.first())
        [email] = mailoutbox
        assert email.to == [job_application.job_seeker.email]

    @pytest.mark.parametrize(
        "refusal_reason,expected",
        [(reason, reason != RefusalReason.AUTO) for reason in RefusalReason],
    )
    def test_refuse_notification_is_applicable(
        self, refusal_reason, expected, django_capture_on_commit_callbacks, mailoutbox
    ):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            refusal_reason=refusal_reason,
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.refuse(user=job_application.to_company.members.first())

        if expected:
            assert [mail.to for mail in mailoutbox] == [
                [job_application.job_seeker.email],
                [job_application.sender.email],
            ]
        else:
            assert [mail.to for mail in mailoutbox] == [[job_application.job_seeker.email]]

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
        assert approval.get_remainder_display() in email.body
        assert approval.user.last_name.upper() in email.body
        assert approval.user.first_name.title() in email.body
        assert approval.user.jobseeker_profile.birthdate.strftime("%d/%m/%Y") in email.body
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
            f"[DEV] PASS IAE pour {job_application.job_seeker.get_full_name()} et avis sur les emplois de l'inclusion"
            == email.subject
        )
        assert "PASS IAE" in email.body

    def test_notifications_deliver_approval_when_not_subject_to_eligibility_rules(self):
        job_application = JobApplicationFactory(with_approval=True, to_company__not_subject_to_eligibility=True)

        email = job_application.notifications_deliver_approval(job_application.to_company.members.first()).build()

        assert "[DEV] Confirmation de l'embauche" == email.subject
        assert "PASS IAE" not in email.body
        assert global_constants.ITOU_HELP_CENTER_URL in email.body

    def test_manually_deliver_approval(self, django_capture_on_commit_callbacks, mailoutbox):
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
        with django_capture_on_commit_callbacks(execute=True):
            job_application.manually_deliver_approval(delivered_by=staff_member)
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_number_sent_at is not None
        assert job_application.approval_manually_delivered_by == staff_member
        assert job_application.approval_manually_refused_at is None
        assert job_application.approval_manually_refused_by is None
        assert len(mailoutbox) == 1

    def test_manually_refuse_approval(self, django_capture_on_commit_callbacks, mailoutbox):
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
        with django_capture_on_commit_callbacks(execute=True):
            job_application.manually_refuse_approval(refused_by=staff_member)
        assert job_application.approval_manually_refused_by == staff_member
        assert job_application.approval_manually_refused_at is not None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_manually_delivered_by is None
        assert job_application.approval_number_sent_at is None
        assert len(mailoutbox) == 1

    def test_cancel_sent_by_prescriber(self, django_capture_on_commit_callbacks, mailoutbox):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationState.ACCEPTED
        )

        cancellation_user = job_application.to_company.active_members.first()
        with django_capture_on_commit_callbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        assert len(mailoutbox) == 2

        # To.
        assert [cancellation_user.email] == mailoutbox[0].to
        assert [job_application.sender.email] == mailoutbox[1].to

        # Body.
        assert "annulée" in mailoutbox[0].body
        assert job_application.sender.get_full_name() in mailoutbox[0].body
        assert job_application.job_seeker.get_full_name() in mailoutbox[0].body
        assert mailoutbox[0].body == mailoutbox[1].body

    def test_for_proxy_notification(self, subtests):
        employer_job_app = JobApplicationFactory(sent_by_another_employer=True)
        prescriber_job_app = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)

        for transition in ["cancel", "postpone", "refuse", "new", "accept"]:
            with subtests.test(transition):
                assert (
                    getattr(employer_job_app, f"notifications_{transition}_for_proxy").structure
                    == employer_job_app.sender_company
                )
                assert (
                    getattr(prescriber_job_app, f"notifications_{transition}_for_proxy").structure
                    == prescriber_job_app.sender_prescriber_organization
                )

    def test_cancel_sent_by_job_seeker(self, django_capture_on_commit_callbacks, mailoutbox):
        # When sent by jobseeker.
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationState.ACCEPTED)

        cancellation_user = job_application.to_company.active_members.first()
        with django_capture_on_commit_callbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        assert len(mailoutbox) == 1

        # To.
        assert [cancellation_user.email] == mailoutbox[0].to

        # Body.
        assert "annulée" in mailoutbox[0].body
        assert job_application.sender.get_full_name() in mailoutbox[0].body
        assert job_application.job_seeker.get_full_name() in mailoutbox[0].body

    def test_cancel_without_sender(self, django_capture_on_commit_callbacks, mailoutbox):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, state=JobApplicationState.ACCEPTED
        )
        # User account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender", "updated_at"])
        cancellation_user = job_application.to_company.active_members.first()
        with django_capture_on_commit_callbacks(execute=True):
            job_application.cancel(user=cancellation_user)
        [email] = mailoutbox
        assert email.to == [cancellation_user.email]


class TestJobApplicationWorkflow:
    SENT_PASS_EMAIL_SUBJECT = "PASS IAE pour"
    ACCEPT_EMAIL_SUBJECT_PROXY = "Candidature acceptée et votre avis sur les emplois de l'inclusion"
    ACCEPT_EMAIL_SUBJECT_JOB_SEEKER = "Candidature acceptée"

    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.API_ESD = {
            "BASE_URL": "https://base.domain",
            "AUTH_BASE_URL": "https://authentication-domain.fr",
            "KEY": "foobar",
            "SECRET": "pe-secret",
        }

    def test_accept_job_application_sent_by_job_seeker_and_make_others_obsolete(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
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
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationState.ACCEPTED).count() == 1
        assert job_seeker.job_applications.filter(state=JobApplicationState.OBSOLETE).count() == 3

        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_obsolete(self, django_capture_on_commit_callbacks, mailoutbox):
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
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())

        assert job_seeker.job_applications.filter(state=JobApplicationState.ACCEPTED).count() == 2
        assert job_seeker.job_applications.filter(state=JobApplicationState.OBSOLETE).count() == 4

        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        """
        When an approval already exists, it is reused.
        """
        job_seeker = JobSeekerFactory(with_pole_emploi_id=True)
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationState.PROCESSING
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval == approval
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_already_existing_valid_approval_with_nir(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        job_seeker = JobSeekerFactory(jobseeker_profile__pole_emploi_id="", jobseeker_profile__birthdate=None)
        approval = ApprovalFactory(user=job_seeker)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker, state=JobApplicationState.PROCESSING
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval == approval
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_forgotten_pole_emploi_id(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
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
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_MANUAL
        # Check sent email.
        assert len(mailoutbox) == 2
        # Email sent to the team.
        assert "PASS IAE requis sur Itou" in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_a_nir_no_pe_approval(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="",
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == job_application.sender_kind
        assert job_application.approval.origin_prescriber_organization_kind == ""
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_with_a_pole_emploi_id_no_pe_approval(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            with_pole_emploi_id=True,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_job_seeker_unregistered_no_pe_approval(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_delivery_mode == JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert job_application.approval.origin_prescriber_organization_kind == ""
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_sent_by_prescriber(self, django_capture_on_commit_callbacks, mailoutbox):
        """
        Accept a job application sent by an "orienteur".
        """
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker__with_pole_emploi_id=True,
        )
        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_application.job_seeker.jobseeker_profile.pole_emploi_id != ""
        with django_capture_on_commit_callbacks(execute=True):
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
        assert len(mailoutbox) == 3
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mailoutbox[2].subject

    def test_accept_job_application_sent_by_authorized_prescriber(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
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
        with django_capture_on_commit_callbacks(execute=True):
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
        assert len(mailoutbox) == 3
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mailoutbox[2].subject

    def test_accept_job_application_sent_by_authorized_prescriber_with_approval_in_waiting_period(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        """
        An authorized prescriber can bypass the waiting period.
        """
        user = JobSeekerFactory(with_pole_emploi_id=True)
        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
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
        with django_capture_on_commit_callbacks(execute=True):
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
        assert len(mailoutbox) == 3
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mailoutbox[2].subject

    def test_accept_job_application_sent_by_prescriber_with_approval_in_waiting_period(self):
        """
        An "orienteur" cannot bypass the waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
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

    def test_accept_job_application_sent_by_job_seeker_in_waiting_period_valid_diagnosis(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        """
        A job seeker with a valid diagnosis can start an IAE path
        even if he's in a waiting period.
        """
        user = JobSeekerFactory()
        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        assert approval.is_in_waiting_period

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=user)
        assert diagnosis.is_valid

        job_application = JobApplicationSentByJobSeekerFactory(job_seeker=user, state=JobApplicationState.PROCESSING)
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert job_application.approval is not None
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_AUTOMATIC
        assert job_application.approval.origin_siae_kind == job_application.to_company.kind
        assert job_application.approval.origin_siae_siret == job_application.to_company.siret
        assert job_application.approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert job_application.approval.origin_prescriber_organization_kind == ""
        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the employer.
        assert self.SENT_PASS_EMAIL_SUBJECT in mailoutbox[0].subject
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[1].subject

    def test_accept_job_application_hiring_after_approval_expires(self):
        """
        To be accepted a job must start while the approval is valid.
        """
        today = timezone.localdate()
        job_application = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.PROCESSING,
            hiring_start_at=today + relativedelta(days=2),
            approval__end_at=today + relativedelta(days=1),
        )

        with pytest.raises(xwf_models.AbortTransition) as raised_exception:
            job_application.accept(user=job_application.to_company.members.first())
        assert str(raised_exception.value) == JobApplicationWorkflow.error_hires_after_pass_invalid

    def test_accept_job_application_by_siae_not_subject_to_eligibility_rules(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        """
        No approval should be delivered for an employer not subject to eligibility rules.
        """
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
        )
        with django_capture_on_commit_callbacks(execute=True):
            job_application.accept(user=job_application.to_company.members.first())
        assert not job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.approval is None
        assert not job_application.approval_number_sent_by_email
        assert job_application.approval_delivery_mode == ""
        # Check sent emails.
        assert len(mailoutbox) == 2
        # Email sent to the job seeker.
        assert self.ACCEPT_EMAIL_SUBJECT_JOB_SEEKER in mailoutbox[0].subject
        # Email sent to the proxy.
        assert self.ACCEPT_EMAIL_SUBJECT_PROXY in mailoutbox[1].subject

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

        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=job_seeker, from_employer=True, author=to_employer_member, author_siae=to_company
        )

        # A valid Pôle emploi ID should trigger an automatic approval delivery.
        assert job_seeker.jobseeker_profile.pole_emploi_id != ""

        job_application.accept(user=to_employer_member)
        assert job_application.to_company.is_subject_to_eligibility_rules
        assert job_application.eligibility_diagnosis == eligibility_diagnosis

    def test_refuse(self, django_capture_on_commit_callbacks, mailoutbox):
        user = JobSeekerFactory()
        kwargs = {"job_seeker": user, "sender": user, "sender_kind": SenderKind.JOB_SEEKER}

        JobApplicationFactory(state=JobApplicationState.PROCESSING, **kwargs)
        JobApplicationFactory(state=JobApplicationState.POSTPONED, **kwargs)

        assert user.job_applications.count() == 2
        assert user.job_applications.pending().count() == 2

        for job_application in user.job_applications.all():
            mailoutbox.clear()
            with django_capture_on_commit_callbacks(execute=True):
                job_application.refuse(user=EmployerFactory())
            # Check sent email.
            assert len(mailoutbox) == 1
            assert "Candidature déclinée" in mailoutbox[0].subject

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
        today = timezone.localdate()

        # Linked employee record with blocking status
        job_application = JobApplicationFactory(with_approval=True, hiring_start_at=(today - relativedelta(days=365)))
        cancellation_user = job_application.to_company.active_members.first()
        EmployeeRecordTransitionLog.log_transition(
            transition=factory.fuzzy.FuzzyChoice(EmployeeRecordTransition.without_asp_exchange()),
            from_state=factory.fuzzy.FuzzyChoice(Status),
            to_state=factory.fuzzy.FuzzyChoice(Status),
            modified_object=EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED),
        )

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

    def test_cancel_delete_employee_record_that_were_not_sent(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)
        EmployeeRecordTransitionLog.log_transition(
            transition=random.choice(list(EmployeeRecordTransition.without_asp_exchange())),
            from_state=random.choice(list(Status)),
            to_state=random.choice(list(Status)),
            modified_object=EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED),
        )

        job_application.cancel(user=job_application.to_company.active_members.first())
        assertQuerySetEqual(EmployeeRecord.objects.filter(job_application=job_application), [])


@pytest.mark.parametrize(
    "transition,from_state",
    [
        pytest.param(transition, from_state, id=f"transition={transition.name} from_state={from_state}")
        for transition in JobApplicationWorkflow.transitions
        for from_state in transition.source
    ],
)
def test_job_application_transitions(transition, from_state):
    job_application = JobApplicationFactory(state=from_state)
    user = job_application.to_company.members.first()
    kwargs = {"user": user}
    if transition.name in ["transfer", "external_transfer"]:
        target_company = CompanyFactory(with_membership=True)
        target_company.members.add(user)
        kwargs["target_company"] = target_company
    getattr(job_application, transition.name)(**kwargs)
    assert job_application.logs.get().transition == transition.name


@pytest.mark.parametrize(
    "transition,from_state",
    [
        pytest.param(transition, from_state, id=f"transition={transition.name} from_state={from_state}")
        for transition in JobApplicationWorkflow.transitions
        for from_state in transition.source
        if transition.name != JobApplicationWorkflow.TRANSITION_EXTERNAL_TRANSFER
        and from_state.name
        not in (
            # Employment relationship between employer and job seeker, it is active.
            JobApplicationState.ACCEPTED,
            # Employer waits for a prior action before to establish an employment relationship.
            JobApplicationState.PRIOR_TO_HIRE,
        )
    ],
)
def test_job_application_transition_unarchives(transition, from_state):
    job_application = JobApplicationFactory(state=from_state, archived_at=timezone.now())
    user = job_application.to_company.members.first()
    kwargs = {"user": user}
    if transition.name in ["transfer", "external_transfer"]:
        target_company = CompanyFactory(with_membership=True)
        target_company.members.add(user)
        kwargs["target_company"] = target_company
    getattr(job_application, transition.name)(**kwargs)
    job_application.refresh_from_db()
    assert job_application.archived_at is None


class TestJobApplicationXlsxExport:
    def test_xlsx_export_contains_the_necessary_info(self, *args, **kwargs):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_seeker = JobSeekerFactory(title=Title.MME)
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            selected_jobs=Appellation.objects.all(),
            eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
        )
        job_application.accept(user=job_application.to_company.members.first())
        request = RequestFactory()
        request.user = job_application.to_company.members.first()

        # The accept transition above will create a valid PASS IAE for the job seeker.
        assert job_seeker.approvals.last().is_valid

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                "MME",
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                excel_date_format(job_seeker.jobseeker_profile.birthdate),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                excel_date_format(job_application.created_at),
                "Candidature acceptée",
                excel_date_format(job_application.hiring_start_at),
                excel_date_format(job_application.hiring_end_at),
                "",  # no reafusal reason
                "oui",  # Eligibility status.
                "non",  # Eligible to SIAE evaluations.
                job_application.approval.number,
                excel_date_format(job_application.approval.start_at),
                excel_date_format(job_application.approval.end_at),
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
                eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
            )
            job_application.accept(user=job_application.to_company.members.first())
        request = RequestFactory()
        request.user = job_application.to_company.members.first()

        assert job_seeker.approvals.last().is_in_waiting_period

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                "MME",
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                excel_date_format(job_seeker.jobseeker_profile.birthdate),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                excel_date_format(job_application.created_at),
                "Candidature acceptée",
                excel_date_format(job_application.hiring_start_at),
                excel_date_format(job_application.hiring_end_at),
                "",  # no reafusal reason
                "non",  # Eligibility status.
                "non",  # Eligible to SIAE evaluations.
                job_application.approval.number,
                excel_date_format(job_application.approval.start_at),
                excel_date_format(job_application.approval.end_at),
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
        job_application.refuse(user=job_application.to_company.members.get())

        request = RequestFactory()
        request.user = job_application.to_company.members.first()

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                job_seeker.title,
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                excel_date_format(job_seeker.jobseeker_profile.birthdate),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                "Candidature spontanée",
                "Candidature spontanée",
                "",
                job_application.sender.get_full_name(),
                excel_date_format(job_application.created_at),
                "Candidature déclinée",
                excel_date_format(job_application.hiring_start_at),
                excel_date_format(job_application.hiring_end_at),
                "Candidat non joignable",
                "oui",  # Eligibility status.
                "non",  # Eligible to SIAE evaluations.
                "",
                "",
                "",
                "",
            ],
        ]

    @freeze_time("2024-07-05")
    def test_auto_prescription_xlsx_export(self):
        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)
        employer = company.members.get()
        start = datetime.date(2024, 7, 5)
        diag = IAEEligibilityDiagnosisFactory(
            from_employer=True,
            job_seeker=job_seeker,
            author_siae=company,
            author=employer,
        )
        approval = ApprovalFactory(start_at=start, user=job_seeker, eligibility_diagnosis=diag)
        JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sender_company=company,
            sender_kind=SenderKind.EMPLOYER,
            sender=employer,
            eligibility_diagnosis=diag,
            approval=approval,
            hiring_start_at=start,
            state=JobApplicationState.ACCEPTED,
        )
        request = RequestFactory()
        request.user = company.members.first()

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                "MME",
                "Doe",
                "Jane",
                "jane.doe@test.local",
                "0612345678",
                datetime.datetime(1990, 1, 1),
                "Rennes",
                "35000",
                "Acme inc.",
                "EI",
                "Candidature spontanée",
                "Ma structure",
                "",
                "John DOE",
                datetime.datetime(2024, 7, 5),
                "Candidature acceptée",
                datetime.datetime(2024, 7, 5),
                datetime.datetime(2026, 7, 5),
                "",
                "oui",  # Eligibility status.
                "oui",  # Eligible to SIAE evaluations.
                approval.number,
                datetime.datetime(2024, 7, 5),
                datetime.datetime(2026, 7, 4),
                "Valide",
            ],
        ]

    def test_xlsx_export_as_prescriber(self, *args, **kwargs):
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=2)
        job_seeker = JobSeekerFactory(title=Title.MME, first_name="Very Secret", last_name="Name")
        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            selected_jobs=Appellation.objects.all(),
            eligibility_diagnosis=IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker),
        )
        prescriber = job_application.sender
        assert prescriber.is_prescriber
        job_application.accept(user=job_application.to_company.members.first())

        # The accept transition above will create a valid PASS IAE for the job seeker.
        assert job_seeker.approvals.last().is_valid

        request = RequestFactory()
        request.user = prescriber
        request.from_authorized_prescriber = False

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                "",
                "N…",
                "V… S…",
                "",
                "",
                "",
                "",
                "",
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Orienteur",
                "",
                job_application.sender.get_full_name(),
                excel_date_format(job_application.created_at),
                "Candidature acceptée",
                excel_date_format(job_application.hiring_start_at),
                excel_date_format(job_application.hiring_end_at),
                "",  # no reafusal reason
                "oui",  # Eligibility status.
                "non",  # Eligible to SIAE evaluations.
                job_application.approval.number,
                excel_date_format(job_application.approval.start_at),
                excel_date_format(job_application.approval.end_at),
                "Valide",
            ],
        ]

        # Give access to the job_seeker's personal information
        job_seeker.created_by = prescriber
        job_seeker.save(update_fields=("created_by",))

        response = stream_xlsx_export(JobApplication.objects.all(), "filename", request=request)
        assert get_rows_from_streaming_response(response) == [
            list(JOB_APPLICATION_XSLX_FORMAT.keys()),
            [
                "MME",
                job_seeker.last_name,
                job_seeker.first_name,
                job_seeker.email,
                job_seeker.phone,
                excel_date_format(job_seeker.jobseeker_profile.birthdate),
                job_seeker.city,
                job_seeker.post_code,
                job_application.to_company.display_name,
                str(job_application.to_company.kind),
                " ".join(a.display_name for a in job_application.selected_jobs.all()),
                "Orienteur",
                "",
                job_application.sender.get_full_name(),
                excel_date_format(job_application.created_at),
                "Candidature acceptée",
                excel_date_format(job_application.hiring_start_at),
                excel_date_format(job_application.hiring_end_at),
                "",  # no reafusal reason
                "oui",  # Eligibility status.
                "non",  # Eligible to SIAE evaluations.
                job_application.approval.number,
                excel_date_format(job_application.approval.start_at),
                excel_date_format(job_application.approval.end_at),
                "Valide",
            ],
        ]

    def test_all_gender_cases_in_export(self):
        assert _resolve_title(title="", nir="") == ""
        assert _resolve_title(title=Title.M, nir="") == Title.M
        assert _resolve_title(title="", nir="1") == Title.M
        assert _resolve_title(title="", nir="2") == Title.MME
        with pytest.raises(KeyError):
            _resolve_title(title="", nir="0")


class TestJobApplicationAdminForm:
    def test_job_application_admin_form_validation(self):
        form_fields_list = [
            "job_seeker",
            "eligibility_diagnosis",
            "geiq_eligibility_diagnosis",
            "create_employee_record",
            "resume",
            "sender",
            "sender_kind",
            "sender_company",
            "sender_prescriber_organization",
            "to_company",
            "state",
            "archived_at",
            "archived_by",
            "selected_jobs",
            "hired_job",
            "message",
            "answer",
            "answer_to_prescriber",
            "refusal_reason",
            "refusal_reason_shared_with_job_seeker",
            "hiring_start_at",
            "hiring_end_at",
            "origin",
            "approval",
            "approval_delivery_mode",
            "approval_number_sent_by_email",
            "approval_number_sent_at",
            "approval_manually_delivered_by",
            "approval_manually_refused_by",
            "approval_manually_refused_at",
            "transferred_at",
            "transferred_by",
            "transferred_from",
            "created_at",
            "processed_at",
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
            "__all__": [{"message": "Émetteur prescripteur manquant.", "code": ""}],
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
        assert ["Émetteur candidat manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_kind = SenderKind.PRESCRIBER
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert [
            "Émetteur du mauvais type.",
            "Le type de l'émetteur de la candidature ne correspond pas au type de l'utilisateur émetteur",
        ] == form.errors["__all__"]
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
        assert ["SIAE émettrice manquante.", "Données incohérentes pour une candidature employeur"] == form.errors[
            "__all__"
        ]
        job_application.sender_company = sender_company

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert [
            "Émetteur du mauvais type.",
            "Le type de l'émetteur de la candidature ne correspond pas au type de l'utilisateur émetteur",
        ] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Émetteur SIAE manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_prescriber_organization = (
            JobApplicationSentByPrescriberOrganizationFactory().sender_prescriber_organization
        )
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert [
            "Organisation du prescripteur émettrice inattendue.",
            "Données incohérentes pour une candidature employeur",
        ] == form.errors["__all__"]
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
        assert [
            "Émetteur du mauvais type.",
            "Le type de l'émetteur de la candidature ne correspond pas au type de l'utilisateur émetteur",
        ] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Émetteur prescripteur manquant."] == form.errors["__all__"]
        job_application.sender = sender

        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Organisation du prescripteur émettrice manquante."] == form.errors["__all__"]
        job_application.sender_prescriber_organization = sender_prescriber_organization

        job_application.sender_company = JobApplicationSentByCompanyFactory().sender_company
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["SIAE émettrice inattendue.", "Données incohérentes pour une candidature prescripteur"] == form.errors[
            "__all__"
        ]
        job_application.sender_company = None

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_applications_sent_by_prescriber_without_organization(self):
        job_application = JobApplicationSentByPrescriberFactory()
        sender = job_application.sender

        job_application.sender = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert [
            "Émetteur du mauvais type.",
            "Le type de l'émetteur de la candidature ne correspond pas au type de l'utilisateur émetteur",
        ] == form.errors["__all__"]

        job_application.sender = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Émetteur prescripteur manquant."] == form.errors["__all__"]
        job_application.sender = sender

        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

        # explicit redundant test
        job_application.sender_prescriber_organization = None
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert form.is_valid()

    def test_application_on_non_job_seeker(self):
        job_application = JobApplicationFactory(eligibility_diagnosis=None)
        job_application.job_seeker = PrescriberFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Impossible de candidater pour cet utilisateur, celui-ci n'est pas un compte candidat"] == form.errors[
            "__all__"
        ]

    def test_application_bad_eligibility_diagnosis_job_seeker(self):
        job_application = JobApplicationFactory()
        job_application.job_seeker = JobSeekerFactory()
        form = JobApplicationAdminForm(model_to_dict(job_application))
        assert not form.is_valid()
        assert ["Le diagnostic d'eligibilité n'appartient pas au candidat de la candidature."] == form.errors[
            "__all__"
        ]


class TestJobApplicationsEnums:
    def test_refusal_reason(self, subtests):
        """Some reasons are kept for history but not displayed to end users."""
        hidden_choices = RefusalReason.hidden()
        for choice in hidden_choices:
            reasons = [choice[0] for choice in RefusalReason.displayed_choices()]
            assert len(reasons) > 0
            with subtests.test(choice.label):
                assert choice.value not in reasons
