import datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from itou.geiq_assessments.models import AssessmentCampaign
from itou.institutions.enums import InstitutionKind
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import (
    AssessmentFactory,
    EmployeeContractFactory,
    EmployeeFactory,
    EmployeePrequalificationFactory,
)
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory


def test_campaign_review_after_submission_constraint():
    june_1st = datetime.date(2024, 6, 1)
    july_1st = datetime.date(2024, 7, 1)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AssessmentCampaign.objects.create(
                year=2023,
                submission_deadline=july_1st,
                review_deadline=june_1st,
            )
    # Use consistent dates
    AssessmentCampaign.objects.create(
        year=2023,
        submission_deadline=june_1st,
        review_deadline=july_1st,
    )


def test_assessment_date_order_constraints():
    assessment = AssessmentFactory(campaign__year=2023)
    previous_field = "created_at"
    for date_field in [
        "contracts_synced_at",
        "contracts_selection_validated_at",
        "submitted_at",
        "grants_selection_validated_at",
        "decision_validated_at",
        "reviewed_at",
        "final_reviewed_at",
    ]:
        previous_field_value = getattr(assessment, previous_field)
        if date_field == "submitted_at":
            assessment.submitted_by = EmployerFactory()
            assessment.summary_document_file = FileFactory()
            assessment.action_financial_assessment_file = FileFactory()
            assessment.structure_financial_assessment_file = FileFactory()
            assessment.geiq_comment = "Bonjour, merci, au revoir !"
        elif date_field == "reviewed_at":
            ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
            assessment.reviewed_by = ddets_membership.user
            assessment.reviewed_by_institution = ddets_membership.institution
            assessment.review_comment = "Bravo !"
        elif date_field == "final_reviewed_at":
            dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
            assessment.final_reviewed_by = dreets_membership.user
            assessment.final_reviewed_by_institution = dreets_membership.institution
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                setattr(assessment, date_field, previous_field_value - datetime.timedelta(hours=1))
                assessment.save()
        setattr(assessment, date_field, previous_field_value + datetime.timedelta(hours=1))
        assessment.save()
        previous_field = date_field


def test_assessment_full_submission_or_no_submission_constraint():
    assessment = AssessmentFactory(
        campaign__year=2023,
        contracts_synced_at=timezone.now() + datetime.timedelta(hours=1),
        contracts_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.submitted_at = timezone.now() + datetime.timedelta(hours=1)
            assessment.save()
    # Add required submission fields
    assessment.submitted_by = EmployerFactory()
    assessment.summary_document_file = FileFactory()
    assessment.structure_financial_assessment_file = FileFactory()
    assessment.action_financial_assessment_file = FileFactory()
    assessment.geiq_comment = "Bonjour, merci, au revoir !"
    assessment.save()


def test_assessment_full_or_no_review_constraint():
    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
            assessment.save()

    # Add missing review fields
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.reviewed_by = ddets_membership.user
    assessment.reviewed_by_institution = ddets_membership.institution
    assessment.review_comment = "Bravo !"
    assessment.save()


def test_assessment_full_or_no_final_review_constraint():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
        reviewed_at=timezone.now() + datetime.timedelta(hours=1),
        reviewed_by=ddets_membership.user,
        reviewed_by_institution=ddets_membership.institution,
        review_comment="Bravo !",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.final_reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
            assessment.save()

    # Add missing review fields
    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.final_reviewed_by = dreets_membership.user
    assessment.final_reviewed_by_institution = dreets_membership.institution
    assessment.save()


def test_employee_full_name():
    employee = EmployeeFactory(first_name="Pré nom ", last_name=" Nom de Famille")
    assert employee.get_full_name() == "NOM DE FAMILLE Pré Nom"


def test_employee_get_prior_actions():
    employee = EmployeeFactory()
    assert employee.get_prior_actions() == []
    EmployeePrequalificationFactory(
        employee=employee,
        start_at=datetime.date(2023, 1, 1),
        end_at=datetime.date(2023, 3, 31),
        other_data={
            "action_pre_qualification": {"id": 3, "libelle": "POE", "libelle_abr": "POE"},
            "nombre_heure_formation": 1,
        },
    )
    assert employee.get_prior_actions() == ["POE (1 heure du 01/01/2023 au 31/03/2023)"]
    EmployeePrequalificationFactory(
        employee=employee,
        start_at=datetime.date(2022, 1, 1),
        end_at=datetime.date(2024, 3, 31),
        other_data={
            "action_pre_qualification": {"id": 5, "libelle": "AUTRE", "libelle_abr": "AUTRE"},
            "autre_type_prequalification_action": "PMSMP",
            "nombre_heure_formation": 12,
        },
    )
    assert employee.get_prior_actions() == [
        "PMSMP (12 heures du 01/01/2022 au 31/03/2024)",
        "POE (1 heure du 01/01/2023 au 31/03/2023)",
    ]


@pytest.mark.parametrize(
    "start,planned_end,end,expected",
    [
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), None, 31),
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), datetime.date(2024, 1, 31), 31),
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), datetime.date(2024, 1, 10), 10),
    ],
)
def test_employee_contract_duration(start, planned_end, end, expected):
    contract = EmployeeContractFactory(start_at=start, planned_end_at=planned_end, end_at=end)
    assert contract.duration().days == expected
