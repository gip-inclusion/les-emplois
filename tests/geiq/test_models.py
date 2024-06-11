import datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from itou.geiq.enums import ReviewState
from itou.geiq.models import ImplementationAssessmentCampaign
from itou.institutions.enums import InstitutionKind
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionFactory

from .factories import EmployeeFactory, ImplementationAssessmentFactory, PrequalificationFactory


def test_campaign_review_after_submission_constraint():
    june_1st = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
    july_1st = datetime.datetime(2024, 7, 1, tzinfo=datetime.UTC)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ImplementationAssessmentCampaign.objects.create(
                year=2023,
                submission_deadline=july_1st,
                review_deadline=june_1st,
            )
    # Use consistent dates
    ImplementationAssessmentCampaign.objects.create(
        year=2023,
        submission_deadline=june_1st,
        review_deadline=july_1st,
    )


def test_assessment_full_submission_or_no_submission_constraint():
    assessment = ImplementationAssessmentFactory(campaign__year=2023)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.submitted_at = timezone.now()
            assessment.save()
    # Add required submission fields
    assessment.last_synced_at = timezone.now() - datetime.timedelta(days=1)
    assessment.activity_report_file = FileFactory()
    assessment.save()


def test_assessment_reviewed_at_only_after_submitted_at_constraint():
    assessment = ImplementationAssessmentFactory(
        campaign__year=2023,
        submitted_at=timezone.now(),
        last_synced_at=timezone.now() - datetime.timedelta(days=1),
        activity_report_file=FileFactory(),
    )

    institution = InstitutionFactory(kind=InstitutionKind.DDETS_GEIQ)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.review_state = ReviewState.ACCEPTED
            assessment.review_institution = institution
            assessment.review_comment = "Bravo !"
            assessment.reviewed_at = assessment.submitted_at - datetime.timedelta(hours=1)
            assessment.save()
    # Use a consistent review date
    assessment.reviewed_at = assessment.submitted_at + datetime.timedelta(hours=1)
    assessment.save()


def test_assessment_full_review_or_no_review_constraint():
    assessment = ImplementationAssessmentFactory(
        campaign__year=2023,
        submitted_at=timezone.now(),
        last_synced_at=timezone.now() - datetime.timedelta(days=1),
        activity_report_file=FileFactory(),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            assessment.reviewed_at = assessment.submitted_at + datetime.timedelta(hours=1)
            assessment.save()

    # Add missing review fields
    assessment.review_state = ReviewState.ACCEPTED
    assessment.review_institution = InstitutionFactory(kind=InstitutionKind.DDETS_GEIQ)
    assessment.review_comment = "Bravo !"
    assessment.save()


def test_employee_full_name():
    employee = EmployeeFactory(first_name="Pré nom ", last_name=" Nom de Famille")
    assert employee.get_full_name() == "Pré Nom NOM DE FAMILLE"


def test_employee_prior_actions():
    employee = EmployeeFactory()
    assert employee.display_prior_actions() == ""
    PrequalificationFactory(
        employee=employee,
        start_at=datetime.date(2023, 1, 1),
        end_at=datetime.date(2023, 3, 31),
        other_data={"action_pre_qualification": {"id": 3, "libelle": "POE", "libelle_abr": "POE"}},
    )
    assert employee.display_prior_actions() == "POE (2023)"
    PrequalificationFactory(
        employee=employee,
        start_at=datetime.date(2022, 1, 1),
        end_at=datetime.date(2024, 3, 31),
        other_data={
            "action_pre_qualification": {"id": 5, "libelle": "AUTRE", "libelle_abr": "AUTRE"},
            "autre_type_prequalification_action": "PMSMP",
        },
    )
    assert employee.display_prior_actions() == "PMSMP (2022-2024), POE (2023)"
