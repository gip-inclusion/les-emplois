import datetime

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.companies.enums import ProSupportReportBarrier, ProSupportReportOrientation, ProSupportReportSolution
from itou.companies.models import ProSupportReport
from itou.users.models import User
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    ContractFactory,
    ProSupportReportFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


@pytest.fixture
def membership():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True)


def end_of_journey_contract(company, end_date):
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date, end_at=timezone.localdate())
    return contract


def create_url(job_seeker):
    return reverse("job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id})


def report_url(report):
    return reverse("job_seekers_views:pro_support_report", kwargs={"public_id": report.public_id})


def assert_shows_report(response, report):
    assertContains(response, f'href="{report_url(report)}?back_url=')
    assertNotContains(response, 'id="pro-support-report-form"')


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
    client, mailoutbox, membership, end_date, hired_elsewhere, situation, has_solution, answer
):
    contract = end_of_journey_contract(membership.company, end_date)
    if hired_elsewhere:
        ContractFactory(job_seeker=contract.job_seeker, start_date=timezone.localdate())
    advisor = JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker, prescriber_organization=PrescriberOrganizationFactory(authorized=True)
    ).professional
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
    # The authorized prescriber is notified.
    assert [email.to for email in mailoutbox] == [[advisor.email]]

    # Sent reports cannot be modified: the page shows the report instead.
    assert_shows_report(client.get(create_url(contract.job_seeker)), report)


@freeze_time("2026-01-15")
def test_create_pro_support_report_after_renewal_for_employer(client, membership):
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    previous_report = ProSupportReportFactory(
        contract=contract,
        contract_end_date=datetime.date(2026, 1, 25),
        created_at=timezone.now() - datetime.timedelta(days=30),
    )
    client.force_login(membership.user)
    assert_shows_report(client.get(create_url(contract.job_seeker)), previous_report)

    contract.end_date = datetime.date(2026, 2, 10)
    contract.save(update_fields=["end_date", "updated_at"])
    response = client.post(
        create_url(contract.job_seeker),
        data={
            "barriers": [ProSupportReportBarrier.MOBILITY],
            "autonomy": "3",
            "has_solution": "True",
            "solution": ProSupportReportSolution.TRAINING,
        },
    )
    assertRedirects(
        response,
        reverse("job_seekers_views:details", kwargs={"public_id": contract.job_seeker.public_id}),
        fetch_redirect_response=False,
    )
    report = ProSupportReport.objects.exclude(pk=previous_report.pk).get()
    assert report.contract == contract
    assert report.contract_end_date == datetime.date(2026, 2, 10)
    assert_shows_report(client.get(create_url(contract.job_seeker)), report)

    # The card shows the new report.
    details_url = reverse("job_seekers_views:details", kwargs={"public_id": contract.job_seeker.public_id})
    response = client.get(details_url)
    assertContains(response, f'href="{report_url(report)}?back_url={details_url}"')
    assertNotContains(response, f'href="{report_url(previous_report)}?back_url={details_url}"')

    # The previous report can still be read, with its own end date.
    response = client.get(report_url(previous_report))
    assertContains(response, "En cours, fin le 25/01/2026")


@freeze_time("2026-01-15")
def test_create_pro_support_report_when_contract_end_date_moves_for_employer(client, membership):
    report_end_date = datetime.date(2026, 2, 10)
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    report = ProSupportReportFactory(contract=contract, contract_end_date=report_end_date)
    client.force_login(membership.user)

    # The contract end date was brought forward since the report.
    assert_shows_report(client.get(create_url(contract.job_seeker)), report)

    # Then it is extended, without going past the end date of the report.
    contract.end_date = report_end_date
    contract.save(update_fields=["end_date", "updated_at"])
    assert_shows_report(client.get(create_url(contract.job_seeker)), report)

    # Then it is extended past the end date of the report.
    contract.end_date = report_end_date + datetime.timedelta(days=2)
    contract.save(update_fields=["end_date", "updated_at"])
    assert client.get(create_url(contract.job_seeker)).status_code == 200


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
    "contract_company,end_date",
    [
        ("current", datetime.date(2026, 2, 15)),
        ("other", datetime.date(2026, 2, 15)),
        ("unrelated", datetime.date(2026, 1, 25)),
    ],
    ids=[
        "not_at_the_end_of_journey",
        "not_at_the_end_of_journey_in_another_company_of_the_employer",
        "contract_with_a_company_the_employer_is_not_a_member_of",
    ],
)
def test_create_pro_support_report_not_found_for_employer(client, membership, contract_company, end_date):
    other_company = CompanyMembershipFactory(user=membership.user, company__subject_to_iae_rules=True).company
    company = {"current": membership.company, "other": other_company, "unrelated": CompanyFactory()}[contract_company]
    contract = end_of_journey_contract(company, end_date)
    client.force_login(membership.user)
    client.post(
        reverse("dashboard:switch_organization"), {"organization_key": membership.company.organization_switch_key}
    )

    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 404


@freeze_time("2026-01-15")
def test_create_pro_support_report_already_filled_in_by_a_coworker(client, membership):
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    coworker = CompanyMembershipFactory(company=membership.company).user
    report = ProSupportReportFactory(
        contract=contract,
        contract_end_date=contract.end_date,
        author=coworker,
        created_at=datetime.datetime(2026, 1, 13, tzinfo=datetime.UTC),
    )
    client.force_login(membership.user)
    url = create_url(contract.job_seeker)

    response = client.get(url)
    assertContains(
        response,
        f"Le bilan d’accompagnement de ce contrat a déjà été rempli le 13/01/2026 par {coworker.get_full_name()}.",
    )
    assert_shows_report(response, report)

    # Both may have opened the form before the report was sent.
    response = client.post(
        url, data={"autonomy": "3", "has_solution": "True", "solution": ProSupportReportSolution.TRAINING}
    )
    assert_shows_report(response, report)
    assert ProSupportReport.objects.get() == report


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "current_company_traits",
    [{"subject_to_iae_rules": True}, {"not_subject_to_iae_rules": True}],
    ids=["from_another_siae", "from_a_non_iae_company"],
)
def test_create_pro_support_report_from_another_company_of_the_employer(client, membership, current_company_traits):
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    current_company = CompanyFactory(**current_company_traits)
    CompanyMembershipFactory(user=membership.user, company=current_company)
    client.force_login(membership.user)
    client.post(
        reverse("dashboard:switch_organization"), {"organization_key": current_company.organization_switch_key}
    )
    url = create_url(contract.job_seeker)

    response = client.get(url)
    assertContains(
        response,
        f"Connectez-vous à la structure {membership.company.display_name} pour remplir le bilan d’accompagnement",
    )
    assertContains(response, f'<form action="{reverse("dashboard:switch_organization")}?next_url={url}"')
    assertNotContains(response, 'id="pro-support-report-form"')

    # The report cannot be sent from the other company.
    response = client.post(
        url, data={"autonomy": "3", "has_solution": "True", "solution": ProSupportReportSolution.TRAINING}
    )
    assert response.status_code == 200
    assert not ProSupportReport.objects.exists()

    response = client.post(
        f"{reverse('dashboard:switch_organization')}?next_url={url}",
        {"organization_key": membership.company.organization_switch_key},
    )
    assertRedirects(response, url, fetch_redirect_response=False)
    assertContains(client.get(url), 'id="pro-support-report-form"')


@freeze_time("2026-01-15")
def test_create_pro_support_report_already_filled_in_from_another_company_of_the_employer(client, membership):
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    report = ProSupportReportFactory(contract=contract, contract_end_date=contract.end_date)
    current_company = CompanyMembershipFactory(user=membership.user, company__subject_to_iae_rules=True).company
    client.force_login(membership.user)
    client.post(
        reverse("dashboard:switch_organization"), {"organization_key": current_company.organization_switch_key}
    )

    # The report can only be read from its company.
    response = client.get(create_url(contract.job_seeker))
    assertContains(response, f"Connectez-vous à la structure {membership.company.display_name}")
    assertNotContains(response, report_url(report))


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "user_factory,status_code",
    [
        (lambda: CompanyMembershipFactory(company__not_subject_to_iae_rules=True).user, 404),
        (lambda: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(), 403),
        (lambda: PrescriberOrganizationFactory(with_membership=True).members.get(), 403),
        (JobSeekerFactory, 403),
    ],
    ids=["non_iae_employer", "authorized_prescriber", "prescriber", "job_seeker"],
)
def test_create_pro_support_report_not_for_other_roles(client, user_factory, status_code):
    contract = end_of_journey_contract(
        CompanyFactory(subject_to_iae_rules=True), timezone.localdate() + datetime.timedelta(days=10)
    )
    client.force_login(user_factory())

    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == status_code


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
                "La structure recommande une orientation <strong>socio-professionnelle</strong>.",
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


def advisor_who_created_the_job_seeker(report):
    prescriber = advisor_organization(report, authorized=False).members.get()
    User.objects.filter(pk=report.job_seeker_id).update(created_by=prescriber)
    return prescriber


@pytest.mark.parametrize(
    "user_factory,status_code",
    [
        (lambda report: advisor_organization(report).members.get(), 200),
        (lambda report: advisor_organization(report, ended=True).members.get(), 200),
        (lambda report: PrescriberMembershipFactory(organization=advisor_organization(report)).user, 200),
        (lambda report: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(), 404),
        (lambda report: advisor_organization(report, authorized=False).members.get(), 404),
        (advisor_who_created_the_job_seeker, 404),
        (lambda report: CompanyMembershipFactory().user, 404),
        (lambda report: report.job_seeker, 403),
    ],
    ids=[
        "authorized_prescriber_advisor",
        "authorized_prescriber_former_advisor",
        "coworker_of_the_advisor",
        "authorized_prescriber_not_advisor",
        "prescriber_advisor_who_cannot_view_personal_information",
        "prescriber_advisor_who_can_view_personal_information",
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
@pytest.mark.parametrize(
    "contract_end_date,end_of_contract_title",
    [
        (datetime.date(2026, 1, 25), "Ce bénéficiaire arrive en fin de contrat de travail"),
        (datetime.date(2026, 1, 10), "Le contrat de travail de ce bénéficiaire a pris fin"),
    ],
    ids=["contract_ends_soon", "contract_ended"],
)
def test_pro_support_report_banner_on_job_seeker_card_for_advisor(client, contract_end_date, end_of_contract_title):
    report = ProSupportReportFactory(contract__end_date=contract_end_date)
    ApprovalFactory(user=report.job_seeker, start_at=report.contract.start_date, end_at=datetime.date(2026, 6, 1))
    details_url = reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id})

    client.force_login(advisor_organization(report).members.get())
    response = client.get(details_url)
    assertContains(response, "Bilan d’accompagnement disponible")
    assertContains(response, f'href="{report_url(report)}?back_url={details_url}"')
    # It takes the place of the end-of-contract banner.
    assertNotContains(response, end_of_contract_title)

    # A renewal ending soon is not covered by the report on the previous contract.
    ContractFactory(
        job_seeker=report.job_seeker,
        company=report.company,
        start_date=datetime.date(2026, 1, 26),
        end_date=datetime.date(2026, 2, 10),
    )
    response = client.get(details_url)
    assertNotContains(response, "Bilan d’accompagnement disponible")
    assertContains(response, "Ce bénéficiaire arrive en fin de contrat de travail")
    assertContains(response, "10/02/2026")

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
    assertContains(response, f'href="{report_url(report)}?back_url={details_url}"')

    client.force_login(CompanyMembershipFactory().user)
    response = client.get(details_url)
    assertNotContains(response, "Bilan d’accompagnement disponible")


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "contract_end_date,report_banner_count",
    [
        (datetime.date(2026, 2, 10), 0),
        (datetime.date(2026, 6, 1), 1),
        (datetime.date(2026, 1, 20), 1),
    ],
    ids=["contract_renewed_ending_soon", "contract_renewed_not_ending_soon", "contract_end_date_brought_forward"],
)
@pytest.mark.parametrize(
    "user_factory",
    [
        lambda report: advisor_organization(report).members.get(),
        lambda report: CompanyMembershipFactory(company=report.company).user,
    ],
    ids=["advisor", "employer"],
)
def test_pro_support_report_banner_when_contract_end_date_moves(
    client, contract_end_date, report_banner_count, user_factory
):
    report = ProSupportReportFactory(
        contract__end_date=datetime.date(2026, 1, 25), contract_end_date=datetime.date(2026, 1, 25)
    )
    ApprovalFactory(user=report.job_seeker, start_at=report.contract.start_date, end_at=datetime.date(2026, 6, 1))
    report.contract.end_date = contract_end_date
    report.contract.save(update_fields=["end_date", "updated_at"])

    client.force_login(user_factory(report))
    response = client.get(reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id}))
    assertContains(response, "Bilan d’accompagnement disponible", count=report_banner_count)


@freeze_time("2026-01-15")
def test_pro_support_report_banner_shows_the_report_on_the_last_contract_for_advisor(client):
    report_on_last_contract = ProSupportReportFactory(contract__end_date=datetime.date(2026, 2, 10))
    job_seeker = report_on_last_contract.job_seeker
    ApprovalFactory(user=job_seeker, start_at=datetime.date(2025, 6, 1), end_at=datetime.date(2026, 6, 1))
    # A more recent report, on a contract with another company ending earlier.
    report_on_previous_contract = ProSupportReportFactory(
        contract__job_seeker=job_seeker,
        contract__end_date=datetime.date(2026, 2, 1),
        created_at=report_on_last_contract.created_at + datetime.timedelta(days=1),
    )
    details_url = reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    client.force_login(advisor_organization(report_on_last_contract).members.get())
    response = client.get(details_url)
    assertContains(response, f'href="{report_url(report_on_last_contract)}?back_url={details_url}"')
    assertNotContains(response, f'href="{report_url(report_on_previous_contract)}?back_url={details_url}"')


@freeze_time("2026-01-15")
def test_pro_support_report_banner_with_a_newer_contract_without_end_date_for_advisor(client):
    report = ProSupportReportFactory(contract__end_date=datetime.date(2026, 1, 25))
    ApprovalFactory(user=report.job_seeker, start_at=report.contract.start_date, end_at=datetime.date(2026, 6, 1))
    ContractFactory(job_seeker=report.job_seeker, start_date=datetime.date(2026, 1, 10), end_date=None)

    client.force_login(advisor_organization(report).members.get())
    response = client.get(reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id}))
    assertContains(response, f'href="{report_url(report)}?back_url=')
