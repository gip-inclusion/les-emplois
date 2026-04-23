import datetime
import random

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from freezegun import freeze_time

from itou.geiq_assessments.enums import AssessmentState, AssessmentTransition
from itou.geiq_assessments.models import AssessmentCampaign, AssessmentTransitionLog
from itou.institutions.enums import InstitutionKind
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import (
    AssessmentCampaignFactory,
    AssessmentFactory,
    EmployeeContractFactory,
    EmployeeFactory,
    EmployeePrequalificationFactory,
)
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory


def test_campaign_is_open_property():
    today = timezone.localdate()
    # Campaign not open yet
    campaign = AssessmentCampaignFactory(
        year=today.year,
        opening_date=today + datetime.timedelta(days=1),
        submission_deadline=today + datetime.timedelta(days=30),
    )
    assert not campaign.is_open

    # Campaign currently open
    campaign = AssessmentCampaignFactory(
        year=today.year + 1,
        opening_date=today - datetime.timedelta(days=1),
        submission_deadline=today + datetime.timedelta(days=1),
    )
    assert campaign.is_open

    # Campaign closed (submission deadline passed)
    campaign = AssessmentCampaignFactory(
        year=today.year + 2,
        opening_date=today - datetime.timedelta(days=30),
        submission_deadline=today - datetime.timedelta(days=1),
    )
    assert not campaign.is_open


def test_campaign_date_constraints():
    june_1st = datetime.date(2024, 6, 1)
    june_2nd = datetime.date(2024, 6, 2)
    july_1st = datetime.date(2024, 7, 1)
    with pytest.raises(IntegrityError, match=r".*geiq_review_after_submission.*"):
        with transaction.atomic():
            AssessmentCampaign.objects.create(
                year=2023,
                # Submission deadline must be earlier than the review deadline.
                opening_date=june_1st,
                submission_deadline=july_1st,
                review_deadline=june_2nd,
            )
    with pytest.raises(IntegrityError, match=r".*geiq_opening_before_submission.*"):
        with transaction.atomic():
            AssessmentCampaign.objects.create(
                year=2023,
                # Opening date must be earlier than the submission deadline.
                opening_date=june_2nd,
                submission_deadline=june_1st,
                review_deadline=july_1st,
            )
    # Use consistent dates
    AssessmentCampaign.objects.create(
        year=2023,
        opening_date=june_1st,
        submission_deadline=june_2nd,
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
            assessment.state = AssessmentState.SUBMITTED
        elif date_field == "reviewed_at":
            ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
            assessment.reviewed_by = ddets_membership.user
            assessment.reviewed_by_institution = ddets_membership.institution
            assessment.review_comment = "Bravo !"
            assessment.state = AssessmentState.REVIEWED
        elif date_field == "final_reviewed_at":
            dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
            assessment.final_reviewed_by = dreets_membership.user
            assessment.final_reviewed_by_institution = dreets_membership.institution
            assessment.state = AssessmentState.FINAL_REVIEWED
        with pytest.raises(IntegrityError, match=r".*geiq_assessment_.*_before_.*"):
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
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_full_or_no_submission.*"):
        with transaction.atomic():
            assessment.submitted_at = timezone.now() + datetime.timedelta(hours=1)
            assessment.state = AssessmentState.SUBMITTED
            assessment.save()
    # Add required submission fields
    assessment.submitted_by = EmployerFactory()
    assessment.summary_document_file = FileFactory()
    assessment.structure_financial_assessment_file = FileFactory()
    assessment.action_financial_assessment_file = FileFactory()
    assessment.geiq_comment = "Bonjour, merci, au revoir !"
    assessment.save()


def test_assessment_state_submitted_at_constraint():
    assessment = AssessmentFactory(
        campaign__year=2023,
        contracts_synced_at=timezone.now() + datetime.timedelta(hours=1),
        contracts_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_state_submitted_at.*"):
        with transaction.atomic():
            assessment.state = AssessmentState.SUBMITTED
            assessment.save()

    assessment.submitted_at = timezone.now() + datetime.timedelta(hours=1)
    assessment.submitted_by = EmployerFactory()
    assessment.summary_document_file = FileFactory()
    assessment.structure_financial_assessment_file = FileFactory()
    assessment.action_financial_assessment_file = FileFactory()
    assessment.geiq_comment = "Bonjour, merci, au revoir !"
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_state_submitted_at.*"):
        with transaction.atomic():
            assessment.state = AssessmentState.NEW
            assessment.save()

    assessment.state = AssessmentState.SUBMITTED
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
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_full_or_no_review.*"):
        with transaction.atomic():
            assessment.reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
            assessment.state = AssessmentState.REVIEWED
            assessment.save()

    # Add missing review fields
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.reviewed_by = ddets_membership.user
    assessment.reviewed_by_institution = ddets_membership.institution
    assessment.review_comment = "Bravo !"
    assessment.save()


def test_assessment_state_reviewed_at_constraint():
    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_state_reviewed_at.*"):
        with transaction.atomic():
            assessment.state = AssessmentState.REVIEWED
            assessment.save()

    assessment.reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.reviewed_by = ddets_membership.user
    assessment.reviewed_by_institution = ddets_membership.institution
    assessment.review_comment = "Bravo !"
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_state_reviewed_at.*"):
        with transaction.atomic():
            assessment.state = random.choice([AssessmentState.NEW, AssessmentState.SUBMITTED])
            assessment.save()

    assessment.state = AssessmentState.REVIEWED
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
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_full_or_no_final_review.*"):
        with transaction.atomic():
            assessment.final_reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
            assessment.state = AssessmentState.FINAL_REVIEWED
            assessment.save()

    # Add missing review fields
    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.final_reviewed_by = dreets_membership.user
    assessment.final_reviewed_by_institution = dreets_membership.institution
    assessment.save()


def test_assessment_state_final_reviewed_at_constraint():
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
    with pytest.raises(IntegrityError, match=r"geiq_assessment_state_final_reviewed_at.*"):
        with transaction.atomic():
            assessment.state = AssessmentState.FINAL_REVIEWED
            assessment.save()

    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment.final_reviewed_at = assessment.decision_validated_at + datetime.timedelta(hours=1)
    assessment.final_reviewed_by = dreets_membership.user
    assessment.final_reviewed_by_institution = dreets_membership.institution
    with pytest.raises(IntegrityError, match=r".*geiq_assessment_state_final_reviewed_at.*"):
        with transaction.atomic():
            assessment.state = random.choice(
                [AssessmentState.NEW, AssessmentState.SUBMITTED, AssessmentState.REVIEWED]
            )
            assessment.save()

    assessment.state = AssessmentState.FINAL_REVIEWED
    assessment.save()


def test_transition_ask_for_geiq_fix_constraint():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    assessment = AssessmentFactory()

    # No comment with ASK_FOR_GEIQ_FIX
    with pytest.raises(IntegrityError, match=r".*ask_for_geiq_fix_transition_with_comment.*"):
        with transaction.atomic():
            AssessmentTransitionLog.objects.create(
                assessment=assessment,
                user=ddets_membership.user,
                institution=ddets_membership.institution,
                transition=AssessmentTransition.ASK_FOR_GEIQ_FIX,
                from_state=AssessmentState.SUBMITTED,
                to_state=AssessmentState.NEW,
            )

    # A comment for something else than ASK_FOR_GEIQ_FIX
    with pytest.raises(IntegrityError, match=r".*ask_for_geiq_fix_transition_with_comment.*"):
        with transaction.atomic():
            AssessmentTransitionLog.objects.create(
                assessment=assessment,
                user=ddets_membership.user,
                institution=ddets_membership.institution,
                transition=AssessmentTransition.REVIEW,
                from_state=AssessmentState.SUBMITTED,
                to_state=AssessmentState.REVIEWED,
                comment="À revoir.",
            )


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
    "start,planned_end,end,planned_expected,real_expected",
    [
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), None, 31, None),
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), datetime.date(2024, 1, 31), 31, 31),
        (datetime.date(2024, 1, 1), datetime.date(2024, 1, 31), datetime.date(2024, 1, 10), 31, 10),
    ],
)
def test_employee_contract_durations(start, planned_end, end, planned_expected, real_expected):
    contract = EmployeeContractFactory(start_at=start, planned_end_at=planned_end, end_at=end)
    assert contract.planned_duration().days == planned_expected
    if real_expected is None:
        assert contract.real_duration() is None
    else:
        assert contract.real_duration().days == real_expected


def test_employee_contract_nb_of_days():
    employee = EmployeeFactory()
    campaign_year = employee.assessment.campaign.year

    contract = EmployeeContractFactory(
        start_at=datetime.date(campaign_year - 1, random.randint(1, 12), random.randint(1, 28)),
        planned_end_at=datetime.date(campaign_year + 1, random.randint(1, 12), random.randint(1, 28)),
        end_at=None,
    )
    assert contract.nb_days_in_previous_year()
    assert contract.nb_days_in_campaign_year
    assert contract.nb_days_in_following_year()
    assert (
        contract.nb_days_in_previous_year() + contract.nb_days_in_campaign_year + contract.nb_days_in_following_year()
        == contract.planned_duration().days
    )

    # Check that planned_end_at is ignored if end_at is defined
    contract = EmployeeContractFactory(
        start_at=datetime.date(campaign_year - 1, random.randint(1, 12), random.randint(1, 28)),
        planned_end_at=datetime.date(campaign_year, random.randint(1, 12), random.randint(1, 28)),
        end_at=datetime.date(campaign_year + 1, random.randint(1, 12), random.randint(1, 28)),
    )
    assert contract.nb_days_in_previous_year()
    assert contract.nb_days_in_campaign_year
    assert contract.nb_days_in_following_year()
    assert (
        contract.nb_days_in_previous_year() + contract.nb_days_in_campaign_year + contract.nb_days_in_following_year()
        == contract.real_duration().days
    )


def test_employee_contract_antenna_department():
    antenna_contract = EmployeeContractFactory(
        employee__assessment__label_geiq_post_code="54321",
        other_data={"antenne": {"id": 123, "nom": "Antenne de fourmi", "cp": "12345"}},
    )
    assert antenna_contract.antenna_department() == "12"
    geiq_contract = EmployeeContractFactory(
        employee=antenna_contract.employee,
        other_data={"antenne": {"id": 0, "nom": "Le siège"}},
    )
    assert geiq_contract.antenna_department() == "54"


def test_assessment_label_antenna_names():
    assessment = AssessmentFactory.build(
        label_geiq_post_code="54321",
        with_main_geiq=True,
        label_antennas=[
            {"id": 123, "name": "Antenne de fourmi", "post_code": "12345"},
            {"id": 456, "name": "Antenne de télévision"},
        ],
    )
    assert assessment.label_antenna_names() == [
        "Siège (54)",
        "Antenne de fourmi (12)",
        "Antenne de télévision (département non disponible)",
    ]

    assessment.label_geiq_post_code = ""
    assert assessment.label_antenna_names() == [
        "Siège (département non disponible)",
        "Antenne de fourmi (12)",
        "Antenne de télévision (département non disponible)",
    ]

    assessment.label_geiq_post_code = "12345"
    assessment.with_main_geiq = False
    assert assessment.label_antenna_names() == [
        "Antenne de fourmi (12)",
        "Antenne de télévision (département non disponible)",
    ]


def test_transition_submit():
    assessment = AssessmentFactory(campaign__year=2023, with_submission_requirements=True)
    assert assessment.state == AssessmentState.NEW

    assessment.submit(user=EmployerFactory())

    transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
    assert transition.assessment.state == AssessmentState.SUBMITTED
    assert transition.transition == AssessmentTransition.SUBMIT
    assert transition.user == transition.assessment.submitted_by
    assert transition.institution is None
    assert transition.timestamp == transition.assessment.submitted_at


def test_transition_review():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    with freeze_time(timezone.now() - datetime.timedelta(hours=1)):
        assessment = AssessmentFactory(
            campaign__year=2023,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=1),
            submitted_by=EmployerFactory(),
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
            review_comment="Bravo !",
        )
    assert assessment.state == AssessmentState.SUBMITTED

    assessment.review(user=ddets_membership.user, institution=ddets_membership.institution)

    transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
    assert transition.assessment.state == AssessmentState.REVIEWED
    assert transition.transition == AssessmentTransition.REVIEW
    assert transition.user == ddets_membership.user
    assert transition.institution == ddets_membership.institution
    assert transition.timestamp == transition.assessment.reviewed_at


def test_transition_ask_for_institution_fix():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
    with freeze_time(timezone.now() - datetime.timedelta(hours=1)):
        assessment = AssessmentFactory(
            campaign__year=2023,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=1),
            submitted_by=EmployerFactory(),
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
            review_comment="Bravo !",
            reviewed_at=timezone.now() + datetime.timedelta(hours=1),
            reviewed_by=ddets_membership.user,
            reviewed_by_institution=ddets_membership.institution,
        )
    assert assessment.state == AssessmentState.REVIEWED

    assessment.ask_for_institution_fix(user=dreets_membership.user, institution=dreets_membership.institution)

    transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
    assert transition.assessment.state == AssessmentState.SUBMITTED
    assert transition.transition == AssessmentTransition.ASK_FOR_INSTITUTION_FIX
    assert transition.user == dreets_membership.user
    assert transition.institution == dreets_membership.institution


def test_transition_ask_for_geiq_fix():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)

    # DDETS sends back to GEIQ for correction
    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    contract = EmployeeContractFactory(
        employee__assessment=assessment,
        allowance_requested=True,
        allowance_granted=True,
    )
    assert assessment.state == AssessmentState.SUBMITTED

    assessment.ask_for_geiq_fix(
        user=ddets_membership.user, institution=ddets_membership.institution, comment="À revoir."
    )

    transition = AssessmentTransitionLog.objects.get()
    assert assessment.state == AssessmentState.NEW
    assert transition.transition == AssessmentTransition.ASK_FOR_GEIQ_FIX
    assert transition.user == ddets_membership.user
    assert transition.institution == ddets_membership.institution
    assert transition.comment == "À revoir."
    contract.refresh_from_db()
    assert contract.allowance_requested is True
    assert contract.allowance_granted is False

    # DREETS sends back to GEIQ for correction
    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
        review_comment="Bravo !",
        reviewed_at=timezone.now() + datetime.timedelta(hours=1),
        reviewed_by=ddets_membership.user,
        reviewed_by_institution=ddets_membership.institution,
    )
    contract = EmployeeContractFactory(
        employee__assessment=assessment,
        allowance_requested=True,
        allowance_granted=True,
    )
    assert assessment.state == AssessmentState.REVIEWED

    assessment.ask_for_geiq_fix(
        user=dreets_membership.user, institution=dreets_membership.institution, comment="À revoir."
    )

    transition = AssessmentTransitionLog.objects.first()
    assert assessment.state == AssessmentState.NEW
    assert transition.transition == AssessmentTransition.ASK_FOR_GEIQ_FIX
    assert transition.user == dreets_membership.user
    assert transition.institution == dreets_membership.institution
    contract.refresh_from_db()
    assert contract.allowance_requested is True
    assert contract.allowance_granted is False


def test_transition_ask_for_geiq_fix_with_errors():
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)

    assessment = AssessmentFactory(
        campaign__year=2023,
        with_submission_requirements=True,
        submitted_at=timezone.now() + datetime.timedelta(hours=1),
        submitted_by=EmployerFactory(),
        grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
        decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
    )
    assert assessment.state == AssessmentState.SUBMITTED

    with pytest.raises(IntegrityError, match=r".*ask_for_geiq_fix_transition_with_comment.*"):
        with transaction.atomic():
            assessment.ask_for_geiq_fix(
                user=ddets_membership.user, institution=ddets_membership.institution, comment=""
            )
    assessment.refresh_from_db()
    assert assessment.state == AssessmentState.SUBMITTED
    assert AssessmentTransitionLog.objects.exists() is False

    with pytest.raises(IntegrityError, match=r".*null value in column \"comment\".*"):
        with transaction.atomic():
            assessment.ask_for_geiq_fix(
                user=ddets_membership.user, institution=ddets_membership.institution, comment=None
            )
    assessment.refresh_from_db()
    assert assessment.state == AssessmentState.SUBMITTED
    assert AssessmentTransitionLog.objects.exists() is False


@pytest.mark.parametrize("is_reviewed", [True, False])
def test_transition_final_review(is_reviewed):
    ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
    with freeze_time(timezone.now() - datetime.timedelta(hours=1)):
        assessment = AssessmentFactory(
            campaign__year=2023,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=1),
            submitted_by=EmployerFactory(),
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=1),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=1),
            review_comment="Bravo !",
            reviewed_at=(timezone.now() + datetime.timedelta(hours=1)) if is_reviewed else None,
            reviewed_by=ddets_membership.user if is_reviewed else None,
            reviewed_by_institution=ddets_membership.institution if is_reviewed else None,
        )
    assert assessment.state == AssessmentState.REVIEWED if is_reviewed else AssessmentState.SUBMITTED

    dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
    assessment.final_review(user=dreets_membership.user, institution=dreets_membership.institution)

    transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
    assert transition.assessment.state == AssessmentState.FINAL_REVIEWED
    assert transition.transition == AssessmentTransition.FINAL_REVIEW
    assert transition.user == dreets_membership.user
    assert transition.institution == dreets_membership.institution
    assert transition.timestamp == transition.assessment.final_reviewed_at
