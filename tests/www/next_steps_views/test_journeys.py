import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationRequestDenyReason, ProlongationRequestStatus
from itou.approvals.models import Approval, Suspension
from itou.companies.enums import CompanyKind, ProSupportReportBarrier, ProSupportReportSolution
from itou.companies.models import Company, ProSupportReport
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.job_applications.enums import JobApplicationState, RefusalReason
from itou.next_steps.models import BarrierStatus, JobSeekerBarrier
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    ContractFactory,
)
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.rdv_insertion.factories import InvitationRequestFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture(autouse=True)
def experiment_for_everyone(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True


def journey_url(kind, pk):
    return reverse("next_steps_views:journey", kwargs={"kind": kind, "pk": pk})


NBSP = " "


def checked_barriers(response):
    """The barriers checked on the eligibility journey's barriers step."""
    return [option["value"] for option in response.context["form"].options() if option["checked"]]


def walk(client, url, *answers, **headers):
    """Answer the steps one after the other, as the browser does: previous answers travel with each step."""
    data, shown, response = {}, [], None
    for index, step_answers in enumerate(answers):
        data |= step_answers
        shown += list(step_answers)
        response = client.post(url, {**data, "step": index, "nav": "next", "shown": shown}, **headers)
    return response


def ended_contract(company, days_ago=10):
    end_date = timezone.localdate() - datetime.timedelta(days=days_ago)
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    approval = ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    JobApplicationFactory(
        job_seeker=contract.job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
        approval=approval,
    )
    return contract, approval


REPORT_ANSWERS = [
    {"barriers": [ProSupportReportBarrier.MOBILITY], "other_barrier": "Garde d’enfant"},
    {"autonomy": "3"},
    {"has_solution": "False"},
    {"orientation": "SOCIAL"},
]


# Engine
# ------------------------------------------------------------------------------


def test_off_by_default(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = False
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    assert client.get(journey_url("bilan", contract.job_seeker.public_id)).status_code == 404


def test_unknown_journey_and_other_company(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(CompanyMembershipFactory(company__subject_to_iae_rules=True).company)
    client.force_login(membership.user)
    assert client.get(journey_url("unknown", contract.job_seeker.public_id)).status_code == 404
    assert client.get(journey_url("bilan", contract.job_seeker.public_id)).status_code == 404


def test_drawer_or_page(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    # Loaded by htmx: the drawer content only, with the stepper of the existing component.
    response = client.get(url, **HTMX)
    assertNotContains(response, "<html")
    assertContains(response, '<div class="c-stepper mt-3 mb-0">')
    assertContains(response, "<strong>Étape 1</strong>/5&nbsp;: Freins")
    assertContains(response, f'hx-post="{url}"')
    # Without JavaScript: the same journey as an ordinary page.
    response = client.get(url)
    assertContains(response, "<html")
    assertNotContains(response, "hx-post")


def test_previous_step_keeps_the_answers(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    response = walk(client, url, {"barriers": [ProSupportReportBarrier.MOBILITY]})
    assert response.context["step"].label == "Autonomie"
    response = client.post(
        url, {"barriers": [ProSupportReportBarrier.MOBILITY], "shown": ["barriers"], "step": 1, "nav": "previous"}
    )
    assert response.context["step"].label == "Freins"
    assert response.context["form"]["barriers"].value() == [ProSupportReportBarrier.MOBILITY]


def test_a_step_is_not_left_with_errors(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    response = walk(client, url, {}, {})
    assert response.context["step"].label == "Autonomie"
    assertContains(response, "Ce champ est obligatoire.")


def test_answers_are_validated_again_before_saving(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    # A tampered hidden answer sends the user back to its step, nothing is saved.
    response = walk(client, url, *REPORT_ANSWERS, {"autonomy": "42"})
    assert response.context["step"].label == "Autonomie"
    assert not ProSupportReport.objects.exists()


# Employers
# ------------------------------------------------------------------------------


def test_fill_pro_support_report(client, mailoutbox):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    advisor = JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker, prescriber_organization=PrescriberOrganizationFactory(authorized=True)
    ).professional
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    response = walk(client, url, *REPORT_ANSWERS)
    # The follow-up question matches the answer, then everything is shown before sending.
    assert [step.label for step in response.context["steps"]] == [
        "Freins",
        "Autonomie",
        "La suite",
        "Orientation",
        "Envoi",
    ]
    assertContains(response, "Vérifiez avant d’envoyer")
    # The recipient is named before sending.
    assertContains(response, f"Le bilan sera envoyé à {advisor.get_full_name()}")
    assertContains(response, "Garde d’enfant")
    assert not ProSupportReport.objects.exists()

    response = walk(client, url, *REPORT_ANSWERS, {}, **HTMX)
    assertContains(response, "Bilan envoyé")
    assert response["HX-Trigger"] == "nextStepsChanged"
    report = ProSupportReport.objects.get()
    assert report.contract == contract
    assert report.author == membership.user
    assert report.barriers == [ProSupportReportBarrier.MOBILITY]
    assert report.autonomy == 3
    assert report.orientation == "SOCIAL"
    assert report.solution == ""
    # Same side effects as the existing screen.
    assert [email.to for email in mailoutbox] == [[advisor.email]]
    assertContains(response, f"Il est transmis par e-mail à {advisor.get_full_name()}.")
    # Done: the journey is no longer available.
    assert client.get(url).status_code == 404


def test_fill_pro_support_report_with_a_solution(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract, _approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("bilan", contract.job_seeker.public_id)

    walk(
        client,
        url,
        {"barriers": []},
        {"autonomy": "5"},
        {"has_solution": "True"},
        {"solution": ProSupportReportSolution.TRAINING},
        {},
    )
    report = ProSupportReport.objects.get()
    assert report.solution == ProSupportReportSolution.TRAINING
    assert report.orientation == ""


def test_suspend_approval(client):
    membership = CompanyMembershipFactory(company__kind=CompanyKind.AI)
    contract, approval = ended_contract(membership.company)
    client.force_login(membership.user)
    url = journey_url("suspension", approval.pk)
    end_at_before = approval.end_at

    answers = {
        "start_at": contract.end_date.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "end_at": (contract.end_date + datetime.timedelta(days=90)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "reason": Suspension.Reason.FINISHED_CONTRACT,
        "reason_explanation": "",
    }
    response = walk(client, url, answers)
    assertContains(response, Suspension.Reason.FINISHED_CONTRACT.label)
    assert not approval.suspension_set.exists()

    response = walk(client, url, answers, {})
    assertContains(response, "PASS IAE suspendu")
    suspension = approval.suspension_set.get()
    assert suspension.created_by == membership.user
    assert suspension.reason == Suspension.Reason.FINISHED_CONTRACT
    approval.refresh_from_db()
    assert approval.end_at > end_at_before


def test_job_application_is_read_before_answering(client):
    company = CompanyFactory(with_membership=True, with_jobs=True, subject_to_iae_rules=True)
    job_seeker = JobSeekerFactory()
    ContractFactory(job_seeker=job_seeker, company=company, start_date=datetime.date(2024, 3, 1), end_date=None)
    job_application = JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=company,
        state=JobApplicationState.NEW,
        sent_by_authorized_prescriber=True,
        selected_jobs=company.jobs.all()[:1],
        message="Très motivée pour ce poste.",
    )
    client.force_login(company.members.first())
    url = journey_url("candidature", job_application.pk)

    response = client.get(url, **HTMX)
    # As in the prototype: what to know first, the answer at the next step; the total depends on the answer.
    assert response.context["step"].label == "La candidature"
    assertContains(response, "<strong>Étape 1</strong>&nbsp;: La candidature", html=False)
    assertContains(response, escape(job_application.selected_jobs.first().display_name))
    assertContains(response, job_application.sender.get_full_name())
    assertContains(response, "Très motivée pour ce poste.")
    assertContains(response, "Déjà en contrat chez vous")
    assertContains(response, "Éligibilité")
    assertContains(response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
    assertNotContains(response, 'name="decision"')
    # Reading it changes nothing, as on the existing screen.
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.NEW

    response = walk(client, url, {}, **HTMX)
    assert response.context["step"].label == "Votre réponse"
    assertContains(response, 'name="decision"')


def test_meet_the_job_seeker_or_the_prescriber_before_answering(client):
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True, rdv_solidarites_id=None)
    job_application = JobApplicationFactory(
        to_company=company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(company.members.first())
    url = journey_url("candidature", job_application.pk)

    # Without RDV-Insertion: an e-mail with a proposal to complete, to each of them.
    response = client.get(url, **HTMX)
    assertContains(response, "Prendre rendez-vous")
    assertContains(response, f'href="mailto:{job_application.job_seeker.email}?subject=')
    assertContains(response, f'href="mailto:{job_application.sender.email}?subject=')
    assertNotContains(
        response, reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": job_application.pk})
    )

    # With RDV-Insertion: the job seeker gets the invitation of the existing application page.
    Company.objects.filter(pk=company.pk).update(rdv_solidarites_id=1234)
    response = client.get(url, **HTMX)
    invite_url = reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": job_application.pk})
    assertContains(response, f'hx-post="{invite_url}"')
    assertNotContains(response, f'href="mailto:{job_application.job_seeker.email}?subject=')

    # Already invited: said so, until a new invitation is possible.
    InvitationRequestFactory(company=company, job_seeker=job_application.job_seeker)
    response = client.get(url, **HTMX)
    assertContains(response, "Invitation envoyée")
    assertNotContains(response, f'hx-post="{invite_url}"')


def test_job_application_to_processing_then_postponed(client):
    membership = CompanyMembershipFactory()
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(membership.user)
    url = journey_url("candidature", job_application.pk)

    response = walk(client, url, {}, {"decision": "process"})
    assertContains(response, "Réponse enregistrée")
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.PROCESSING

    response = walk(client, url, {}, {"decision": "postpone"}, {"answer": "Nous revenons vers vous en janvier."})
    assertContains(response, JobApplicationState.POSTPONED.label)
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.POSTPONED
    assert job_application.answer == "Nous revenons vers vous en janvier."


def test_refuse_job_application(client, mailoutbox):
    membership = CompanyMembershipFactory(company__with_jobs=True)
    company = membership.company
    job_description = company.job_description_through.first()
    job_application = JobApplicationFactory(
        to_company=company,
        state=JobApplicationState.PROCESSING,
        sent_by_authorized_prescriber=True,
        selected_jobs=[job_description],
    )
    client.force_login(membership.user)
    url = journey_url("candidature", job_application.pk)

    response = walk(
        client,
        url,
        {},
        {"decision": "refuse"},
        {"refusal_reason": RefusalReason.NO_POSITION, "refusal_reason_shared_with_job_seeker": "on"},
    )
    # As on the existing screen: the steps, the default message of the reason, the job descriptions to close.
    assert [step.label for step in response.context["steps"]] == [
        "La candidature",
        "Votre réponse",
        "Motif",
        "Message à l’usager",
        "Message au prescripteur",
    ]
    assert response.context["form"]["job_seeker_answer"].value().startswith("Bonjour")
    response = walk(
        client,
        url,
        {},
        {"decision": "refuse"},
        {"refusal_reason": RefusalReason.NO_POSITION, "refusal_reason_shared_with_job_seeker": "on"},
        {"job_seeker_answer": "Merci pour votre candidature."},
        {"prescriber_answer": "Plus de poste pour le moment."},
        **HTMX,
    )
    assertContains(response, "Candidature déclinée")
    assertContains(response, escape(job_description.display_name))
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.REFUSED
    assert job_application.refusal_reason == RefusalReason.NO_POSITION
    assert job_application.refusal_reason_shared_with_job_seeker is True
    assert job_application.answer == "Merci pour votre candidature."
    assert job_application.answer_to_prescriber == "Plus de poste pour le moment."
    # Same side effects as the existing screen: notifications and the closed recruitment.
    assert mailoutbox
    job_description.refresh_from_db()
    assert job_description.is_active is False


def test_refuse_job_application_sent_by_the_job_seeker(client):
    membership = CompanyMembershipFactory()
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.PROCESSING, sent_by_job_seeker=True
    )
    client.force_login(membership.user)
    url = journey_url("candidature", job_application.pk)

    response = walk(
        client,
        url,
        {},
        {"decision": "refuse"},
        {"refusal_reason": RefusalReason.DID_NOT_COME},
        {"job_seeker_answer": "Nous n’avons pas pu vous joindre."},
    )
    assertContains(response, "Candidature déclinée")
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.REFUSED
    assert job_application.answer_to_prescriber == ""


def _contract_answers(job_application):
    hiring_start_at = timezone.localdate()
    return {
        "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "hiring_end_at": Approval.get_default_end_date(hiring_start_at).strftime(
            DuetDatePickerWidget.INPUT_DATE_FORMAT
        ),
        "answer": "Bienvenue dans l’équipe.",
        "hired_job": job_application.selected_jobs.first().pk,
    }


@pytest.fixture
def mocked_geocoding(settings, mocker):
    settings.API_GEOPF_BASE_URL = "http://ban-api"
    mocker.patch(
        "itou.utils.apis.geocoding.get_geocoding_data", side_effect=mock_get_geocoding_data_by_ban_api_resolved
    )


def test_accept_job_application_with_a_prescriber_diagnosis(client, mocked_geocoding):
    company = CompanyFactory(with_membership=True, with_jobs=True, subject_to_iae_rules=True)
    employer = company.members.first()
    job_seeker = JobSeekerFactory(
        born_in_france=True, jobseeker_profile__with_pole_emploi_id=True, with_ban_api_mocked_address=True
    )
    IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True)
    job_application = JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=company,
        state=JobApplicationState.PROCESSING,
        sent_by_authorized_prescriber=True,
        selected_jobs=company.jobs.all()[:1],
        hiring_end_at=None,
    )
    client.force_login(employer)
    url = journey_url("candidature", job_application.pk)

    response = walk(client, url, {}, {"decision": "accept"}, _contract_answers(job_application))
    # Nothing missing on the job seeker and a prescriber's diagnosis: the contract, then the confirmation.
    assert [step.label for step in response.context["steps"]] == [
        "La candidature",
        "Votre réponse",
        "Contrat",
        "Confirmer",
    ]
    assertContains(response, "Bienvenue dans l’équipe.")

    response = walk(client, url, {}, {"decision": "accept"}, _contract_answers(job_application), {}, **HTMX)
    assertContains(response, "Candidature acceptée")
    assert response["HX-Trigger"] == "nextStepsChanged"
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.ACCEPTED
    assert job_application.hiring_start_at == timezone.localdate()
    assert job_application.answer == "Bienvenue dans l’équipe."
    # Same as the existing screen: a PASS IAE is delivered.
    assert job_application.approval is not None
    assertContains(response, job_application.approval.number_with_spaces)


def test_accept_job_application_with_the_employer_diagnosis(client, mocked_geocoding):
    company = CompanyFactory(with_membership=True, with_jobs=True, kind=CompanyKind.ACI)
    employer = company.members.first()
    job_seeker = JobSeekerFactory(
        born_in_france=True, jobseeker_profile__with_pole_emploi_id=True, with_ban_api_mocked_address=True
    )
    job_application = JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=company,
        state=JobApplicationState.PROCESSING,
        sent_by_job_seeker=True,
        selected_jobs=company.jobs.all()[:1],
        hiring_end_at=None,
    )
    client.force_login(employer)
    url = journey_url("candidature", job_application.pk)

    response = walk(client, url, {}, {"decision": "accept"}, _contract_answers(job_application))
    # No diagnosis covers the hiring: the employer's criteria come before the confirmation.
    assert [step.label for step in response.context["steps"]] == [
        "La candidature",
        "Votre réponse",
        "Contrat",
        "Éligibilité",
        "Confirmer",
    ]
    response = walk(
        client, url, {}, {"decision": "accept"}, _contract_answers(job_application), {"level_1_1": "on"}, {}
    )
    assertContains(response, "Candidature acceptée")
    diagnosis = EligibilityDiagnosis.objects.get(job_seeker=job_seeker)
    assert diagnosis.author_siae == company
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.ACCEPTED


def test_geiq_hiring_is_handed_over(client):
    membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.PROCESSING, sent_by_job_seeker=True
    )
    client.force_login(membership.user)
    url = journey_url("candidature", job_application.pk)

    response = walk(client, url, {}, {"decision": "accept"})
    assertContains(response, reverse("apply:start-accept", kwargs={"job_application_id": job_application.pk}))
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.PROCESSING


# Prescribers
# ------------------------------------------------------------------------------


def test_grant_prolongation_request(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    prolongation_request = ProlongationRequestFactory(
        prescriber_organization=membership.organization, assigned_to=membership.user
    )
    client.force_login(membership.user)
    url = journey_url("prolongation", prolongation_request.pk)

    response = walk(client, url, {}, {"decision": "grant"}, {})
    assertContains(response, "Prolongation acceptée")
    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.GRANTED
    assert prolongation_request.processed_by == membership.user
    # Already processed: nothing left to do.
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("reason", [ProlongationRequestDenyReason.IAE, ProlongationRequestDenyReason.SIAE])
def test_deny_prolongation_request(client, reason):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    prolongation_request = ProlongationRequestFactory(
        prescriber_organization=membership.organization, assigned_to=membership.user
    )
    client.force_login(membership.user)
    url = journey_url("prolongation", prolongation_request.pk)

    steps = [{}, {"decision": "deny"}, {"reason": reason}, {"reason_explanation": "Lorem ipsum"}]
    if reason == ProlongationRequestDenyReason.IAE:
        # Only this reason asks for the proposed actions, as on the existing screen.
        steps.append({"proposed_actions": ["SOCIAL_PARTNER"], "proposed_actions_explanation": "Lorem ipsum"})
    response = walk(client, url, *steps)
    assertContains(response, "Prolongation refusée")
    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.DENIED
    assert prolongation_request.deny_information.reason == reason


def test_validate_eligibility(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    job_seeker = JobSeekerFactory()
    client.force_login(membership.user)
    url = journey_url("eligibilite", job_seeker.public_id)

    response = client.get(url)
    assertContains(response, "Critères administratifs de niveau 1")
    response = walk(client, url, {"level_1_1": "on"}, {}, {})
    assertContains(response, "Éligibilité validée")
    diagnosis = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker, for_siae=None)
    assert diagnosis.author == membership.user
    assert diagnosis.is_valid


def test_validate_eligibility_states_the_barriers(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    job_seeker = JobSeekerFactory(first_name="Sami")
    rsa = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.RSA)
    client.force_login(membership.user)
    url = journey_url("eligibilite", job_seeker.public_id)

    # The criteria first, then the barriers they hint at, checked, with where each comes from.
    response = walk(client, url, {rsa.key: "on"})
    assertContains(response, "Les freins à lever pour Sami")
    assertContains(response, f"Critère{NBSP}: {rsa.name}")
    assert "FINANCIAL" in checked_barriers(response)
    assert "MOBILITY" not in checked_barriers(response)

    # Not the financial situation, but mobility.
    response = walk(client, url, {rsa.key: "on"}, {"barriers": [ProSupportReportBarrier.MOBILITY]}, {})
    assertContains(response, "Éligibilité validée")
    assertContains(response, f"1 frein à lever{NBSP}: Mobilité.")
    diagnosis = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker, for_siae=None)
    assert sorted(
        JobSeekerBarrier.objects.filter(job_seeker=job_seeker).values_list(
            "barrier", "status", "eligibility_diagnosis", "author", "author_prescriber_organization"
        )
    ) == [
        ("FINANCIAL", BarrierStatus.DISMISSED, diagnosis.pk, membership.user.pk, membership.organization.pk),
        ("MOBILITY", BarrierStatus.CONFIRMED, diagnosis.pk, membership.user.pk, membership.organization.pk),
    ]

    # On the job seeker's page: mobility to work on, confirmed; the financial situation no longer hinted at.
    response = client.get(reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id}))
    barriers = response.context["barriers"]
    assert [card.key for card in barriers.to_work] == [ProSupportReportBarrier.MOBILITY]
    assert [clue.kind for clue in barriers.to_work[0].clues] == ["confirmed"]
    assertContains(response, "à la validation de l’éligibilité")

    # At the next validation, what was stated comes back: mobility checked, the financial situation not.
    response = walk(client, url, {rsa.key: "on"})
    assertContains(response, "Confirmé le")
    assertContains(response, "Écarté le")
    assert "MOBILITY" in checked_barriers(response)
    assert "FINANCIAL" not in checked_barriers(response)


def test_validate_eligibility_without_barriers_hinted(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    job_seeker = JobSeekerFactory()
    client.force_login(membership.user)
    url = journey_url("eligibilite", job_seeker.public_id)
    deld = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.DELD)

    # No barrier hinted at: the step says so, and can be passed.
    response = walk(client, url, {deld.key: "on"})
    assertContains(response, "Aucun frein repéré par les critères.")
    response = walk(client, url, {deld.key: "on"}, {}, {})
    assertContains(response, "Éligibilité validée")
    assert not JobSeekerBarrier.objects.filter(job_seeker=job_seeker).exists()


def test_no_eligibility_journey_with_a_valid_approval(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    approval = ApprovalFactory()
    client.force_login(membership.user)
    assert client.get(journey_url("eligibilite", approval.user.public_id)).status_code == 404


def test_request_pro_support_report_by_email(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(
        end_date=end_date, start_date=end_date - datetime.timedelta(days=200), company__email="siae@example.com"
    )
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker, professional=membership.user, prescriber_organization=membership.organization
    )
    client.force_login(membership.user)
    url = journey_url("demande-bilan", contract.job_seeker.public_id)

    response = client.get(url)
    assertContains(response, "siae@example.com")
    assertContains(response, contract.job_seeker.get_full_name())
    response = walk(client, url, {"subject": "Bilan", "body": "Bonjour, pouvez-vous remplir le bilan ?"})
    assertContains(response, "Votre e-mail est prêt")
    assertContains(response, "mailto:siae@example.com?subject=Bilan&amp;body=Bonjour%2C%20pouvez-vous")


# Action buttons
# ------------------------------------------------------------------------------


def test_action_buttons_open_the_drawer(client):
    membership = CompanyMembershipFactory()
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(membership.user)

    response = client.get(reverse("next_steps_views:todo"))
    url = journey_url("candidature", job_application.pk)
    assertContains(response, f'href="{url}"\n               hx-get="{url}"')
    assertContains(response, 'id="next-step-drawer"')
    assertContains(response, 'hx-trigger="nextStepsChanged from:body"')


# Day progress and next action
# ------------------------------------------------------------------------------


def test_done_today_and_next_action(client):
    membership = CompanyMembershipFactory()
    first, second = (
        JobApplicationFactory(
            to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
        )
        for _ in range(2)
    )
    # A colleague's answer is theirs, not the user's.
    colleague = CompanyMembershipFactory(company=membership.company).user
    JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    ).process(user=colleague)
    client.force_login(membership.user)
    todo_url = reverse("next_steps_views:todo")

    response = client.get(todo_url)
    assertNotContains(response, "Fait aujourd’hui")

    response = walk(client, journey_url("candidature", first.pk), {}, {"decision": "process"}, **HTMX)
    # Keep the momentum: what remains today, and the next action, run in the same drawer.
    assertContains(response, "Plus que 1 action vous attend")
    next_url = journey_url("candidature", second.pk)
    assertContains(response, f'hx-get="{next_url}"')
    assertContains(response, f"Action suivante · {second.job_seeker.first_name}")

    response = client.get(todo_url)
    assertContains(response, "Fait aujourd’hui")
    assertContains(response, "candidature mise à l’étude")
    assert [item.job_seeker for item in response.context["done_today"]] == [first.job_seeker]


def test_done_today_for_a_prescriber(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    prolongation_request = ProlongationRequestFactory(
        prescriber_organization=membership.organization, assigned_to=membership.user
    )
    client.force_login(membership.user)
    walk(client, journey_url("prolongation", prolongation_request.pk), {}, {"decision": "grant"}, {})
    walk(client, journey_url("eligibilite", JobSeekerFactory().public_id), {"level_1_1": "on"}, {}, {})

    response = client.get(reverse("next_steps_views:todo"))
    assert [item.label for item in response.context["done_today"]] == [
        "prolongation acceptée",
        "éligibilité IAE validée",
    ]
