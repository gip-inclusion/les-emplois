import datetime

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.users.enums import ProSupportReportBarrier, ProSupportReportOrientation, ProSupportReportSolution
from itou.users.models import ProSupportReport
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, ContractFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, ProSupportReportFactory


@pytest.fixture
def membership():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True)


def end_of_journey_contract(company, end_date):
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date, end_at=timezone.localdate())
    return contract


def create_url(job_seeker):
    return reverse("job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id})


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "end_date,hired_elsewhere,situation,has_solution,answer",
    [
        (
            datetime.date(2026, 1, 25),
            False,
            "Le contrat arrive à échéance le 25/01/2026.",
            "True",
            {"solution": ProSupportReportSolution.TRAINING},
        ),
        (
            datetime.date(2026, 1, 25),
            True,
            "Le contrat arrive à échéance le 25/01/2026.",
            "True",
            {"solution": ProSupportReportSolution.TRAINING},
        ),
        (
            datetime.date(2026, 1, 5),
            False,
            "Le contrat de travail a pris fin le 05/01/2026.",
            "False",
            {"orientation": ProSupportReportOrientation.SOCIAL},
        ),
    ],
    ids=["contract_ends_soon_with_solution", "contract_ends_soon_hired_elsewhere", "contract_ended_without_solution"],
)
def test_create_pro_support_report_for_employer(
    client, membership, end_date, hired_elsewhere, situation, has_solution, answer
):
    contract = end_of_journey_contract(membership.company, end_date)
    if hired_elsewhere:
        ContractFactory(job_seeker=contract.job_seeker, start_date=timezone.localdate())
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assertContains(response, situation)

    response = client.post(
        create_url(contract.job_seeker),
        data={
            "barriers": [ProSupportReportBarrier.MOBILITY],
            "other_barrier": "Horaires de garde",
            "autonomy": "3",
            "has_solution": has_solution,
            "solution": ProSupportReportSolution.RENEWAL,
            "orientation": ProSupportReportOrientation.PROFESSIONAL,
        }
        | answer,
    )
    assertRedirects(
        response,
        reverse("job_seekers_views:details", kwargs={"public_id": contract.job_seeker.public_id}),
        fetch_redirect_response=False,
    )
    assertMessages(response, [messages.Message(messages.SUCCESS, "Bilan d’accompagnement envoyé")])
    report = ProSupportReport.objects.get()
    assert report.job_seeker == contract.job_seeker
    assert report.company == membership.company
    assert report.author == membership.user
    assert report.contract == contract
    assert report.contract_end_date == contract.end_date
    assert report.barriers == [ProSupportReportBarrier.MOBILITY]
    assert report.other_barrier == "Horaires de garde"
    assert report.autonomy == 3
    # Only the question matching the answer is kept.
    assert report.solution == answer.get("solution", "")
    assert report.orientation == answer.get("orientation", "")

    # Sent reports cannot be modified.
    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 404


@freeze_time("2026-01-15")
def test_create_pro_support_report_shows_the_question_matching_the_answer_for_employer(client, membership):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assertNotContains(response, "Quelle solution est envisagée")
    assertNotContains(response, "Quelle orientation serait la plus adaptée")

    response = client.get(create_url(contract.job_seeker), {"has_solution": "True"})
    assertContains(response, "Quelle solution est envisagée")
    assertNotContains(response, "Quelle orientation serait la plus adaptée")

    response = client.get(create_url(contract.job_seeker), {"has_solution": "False"})
    assertNotContains(response, "Quelle solution est envisagée")
    assertContains(response, "Quelle orientation serait la plus adaptée")


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "data,field,error",
    [
        ({"has_solution": "True"}, "solution", "Ce champ est obligatoire."),
        ({"has_solution": "False"}, "orientation", "Ce champ est obligatoire."),
    ],
    ids=["no_solution", "no_orientation"],
)
def test_create_pro_support_report_errors_for_employer(client, membership, data, field, error):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    client.force_login(membership.user)

    response = client.post(
        create_url(contract.job_seeker),
        data={"barriers": [ProSupportReportBarrier.MOBILITY], "autonomy": "3", "has_solution": "True"} | data,
    )
    assert response.context["form"].errors[field] == [error]
    assert not ProSupportReport.objects.exists()


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "other_company,end_date",
    [(False, datetime.date(2026, 2, 15)), (True, datetime.date(2026, 1, 25))],
    ids=["not_at_the_end_of_journey", "contract_with_another_company"],
)
def test_create_pro_support_report_not_found_for_employer(client, membership, other_company, end_date):
    contract = end_of_journey_contract(CompanyFactory() if other_company else membership.company, end_date)
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 404


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "user_factory",
    [
        lambda: CompanyMembershipFactory(company__not_subject_to_iae_rules=True).user,
        lambda: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(),
        lambda: PrescriberOrganizationFactory(with_membership=True).members.get(),
        JobSeekerFactory,
    ],
    ids=["non_iae_employer", "authorized_prescriber", "prescriber", "job_seeker"],
)
def test_create_pro_support_report_not_for_other_roles(client, user_factory):
    contract = end_of_journey_contract(
        CompanyFactory(subject_to_iae_rules=True), timezone.localdate() + datetime.timedelta(days=10)
    )
    client.force_login(user_factory())

    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 403


def report_url(report):
    return reverse("job_seekers_views:pro_support_report", kwargs={"public_id": report.public_id})


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "answer,expected,not_expected",
    [
        (
            {"barriers": [], "solution": ProSupportReportSolution.TRAINING, "orientation": ""},
            ["Aucun frein identifié", "Entrée en formation"],
            ["Mobilité", "Aucune solution prévue à ce jour"],
        ),
        (
            {
                "barriers": [ProSupportReportBarrier.MOBILITY],
                "other_barrier": "Horaires de garde",
                "orientation": ProSupportReportOrientation.SOCIO_PROFESSIONAL,
            },
            [
                '<strong class="d-block">Mobilité</strong>',
                '<strong class="d-block">Autres freins identifiés\xa0: Horaires de garde</strong>',
                "Aucune solution prévue à ce jour",
                "La structure recommande une orientation socio-professionnelle.",
            ],
            ["Aucun frein identifié", "Entrée en formation"],
        ),
    ],
    ids=["without_barrier_with_solution", "with_barriers_without_solution"],
)
def test_pro_support_report_for_employer(client, answer, expected, not_expected):
    report = ProSupportReportFactory(
        contract__end_date=datetime.date(2026, 1, 5),
        autonomy=3,
        **answer,
    )
    client.force_login(CompanyMembershipFactory(company=report.company).user)

    response = client.get(report_url(report))
    assertContains(response, f"Bilan d’accompagnement de {report.job_seeker.get_inverted_full_name()}")
    assertContains(response, "Terminé le 05/01/2026")
    assertContains(response, '<strong class="d-block">3 sur 5</strong>', html=True)
    assertContains(response, "Il mène la plupart des démarches seul, mais sollicite un accompagnement ponctuel.")
    for text in expected:
        assertContains(response, text)
    for text in not_expected:
        assertNotContains(response, text)


def advisor_organization(report, authorized=True, ended=False):
    organization = PrescriberOrganizationFactory(with_membership=True, authorized=authorized)
    JobSeekerAssignmentFactory(
        job_seeker=report.job_seeker,
        professional=organization.members.get(),
        prescriber_organization=organization,
        ended=ended,
    )
    return organization


@pytest.mark.parametrize(
    "user_factory,status_code",
    [
        (lambda report: advisor_organization(report).members.get(), 200),
        (lambda report: advisor_organization(report, ended=True).members.get(), 200),
        (lambda report: PrescriberMembershipFactory(organization=advisor_organization(report)).user, 200),
        (lambda report: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(), 404),
        (lambda report: advisor_organization(report, authorized=False).members.get(), 404),
        (lambda report: CompanyMembershipFactory().user, 404),
        (lambda report: report.job_seeker, 403),
    ],
    ids=[
        "authorized_prescriber_advisor",
        "authorized_prescriber_former_advisor",
        "coworker_of_the_advisor",
        "authorized_prescriber_not_advisor",
        "prescriber_advisor_who_cannot_view_personal_information",
        "employer_of_another_company",
        "job_seeker",
    ],
)
def test_pro_support_report_access_for_roles(client, user_factory, status_code):
    report = ProSupportReportFactory()
    client.force_login(user_factory(report))

    response = client.get(report_url(report))
    assert response.status_code == status_code


@freeze_time("2026-01-15")
def test_pro_support_report_banner_on_job_seeker_card_for_advisor(client):
    report = ProSupportReportFactory(contract__end_date=datetime.date(2026, 1, 25))
    ApprovalFactory(user=report.job_seeker, start_at=report.contract.start_date, end_at=datetime.date(2026, 6, 1))
    details_url = reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id})

    client.force_login(advisor_organization(report).members.get())
    response = client.get(details_url)
    assertContains(response, "Bilan d’accompagnement disponible")
    assertContains(response, f'href="{report_url(report)}"')
    # It takes the place of the end-of-contract banner.
    assertNotContains(response, "Ce bénéficiaire arrive en fin de contrat de travail")

    client.force_login(PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get())
    response = client.get(details_url)
    assertNotContains(response, "Bilan d’accompagnement disponible")
    assertContains(response, "Ce bénéficiaire arrive en fin de contrat de travail")


@freeze_time("2026-01-15")
def test_pro_support_report_banner_on_job_seeker_card_for_employer(client):
    report = ProSupportReportFactory()
    # A more recent report filled by another company.
    ProSupportReportFactory(
        contract__job_seeker=report.job_seeker, created_at=report.created_at + datetime.timedelta(days=1)
    )
    details_url = reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id})

    client.force_login(CompanyMembershipFactory(company=report.company).user)
    response = client.get(details_url)
    assertContains(response, f'href="{report_url(report)}"')

    client.force_login(CompanyMembershipFactory().user)
    response = client.get(details_url)
    assertNotContains(response, "Bilan d’accompagnement disponible")
