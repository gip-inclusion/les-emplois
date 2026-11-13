import datetime

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.companies.enums import (
    ProSupportReportBarrier,
    ProSupportReportOrientation,
    ProSupportReportRecipientSource,
    ProSupportReportSolution,
)
from itou.companies.models import ProSupportReport
from itou.users.enums import ActionKind
from itou.users.models import User
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import (
    CompanyFactory,
    CompanyMembershipFactory,
    ContractFactory,
    ProSupportReportFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory, PrescriberFactory


NO_RECIPIENT = "Aucun prescripteur habilité n’est rattaché à"
SWITCH_ORGANIZATION = "Me connecter à cette structure"


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
    advisor_membership = PrescriberMembershipFactory(organization__authorized=True)
    JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker,
        professional=advisor_membership.user,
        prescriber_organization=advisor_membership.organization,
        last_action_at=timezone.now() - datetime.timedelta(seconds=10),
    )
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
    assertMessages(
        response,
        [
            messages.Message(
                messages.SUCCESS,
                f"Bilan envoyé à {advisor_membership.user.get_full_name()}, "
                f"de {advisor_membership.organization.display_name}",
            )
        ],
    )
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
    assert [email.to for email in mailoutbox] == [[advisor_membership.user.email]]
    assert report.notified_prescriber == advisor_membership.user
    assert report.notified_prescriber_organization == advisor_membership.organization
    assert report.notified_prescriber_source == ProSupportReportRecipientSource.SUGGESTED

    # The employer is the last advisor
    last_assignment = report.job_seeker.last_assignment
    assert last_assignment.professional == report.author
    assert last_assignment.company == report.company
    assert last_assignment.last_action_kind == ActionKind.FILL_REPORT

    # Sent reports cannot be modified.
    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 404


@freeze_time("2026-01-15")
def test_create_pro_support_report_after_renewal_for_employer(client, membership):
    contract = end_of_journey_contract(membership.company, datetime.date(2026, 1, 25))
    previous_report = ProSupportReportFactory(
        contract=contract,
        contract_end_date=datetime.date(2026, 1, 25),
        created_at=timezone.now() - datetime.timedelta(days=30),
    )
    client.force_login(membership.user)
    assert client.get(create_url(contract.job_seeker)).status_code == 404

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
    assert client.get(create_url(contract.job_seeker)).status_code == 404

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
    ProSupportReportFactory(contract=contract, contract_end_date=report_end_date)
    client.force_login(membership.user)

    # The contract end date was brought forward since the report.
    assert client.get(create_url(contract.job_seeker)).status_code == 404

    # Then it is extended, without going past the end date of the report.
    contract.end_date = report_end_date
    contract.save(update_fields=["end_date", "updated_at"])
    assert client.get(create_url(contract.job_seeker)).status_code == 404

    # Then it is extended past the end date of the report.
    contract.end_date = report_end_date + datetime.timedelta(days=2)
    contract.save(update_fields=["end_date", "updated_at"])
    assert client.get(create_url(contract.job_seeker)).status_code == 200


@freeze_time("2026-01-15")
def test_create_pro_support_report_shows_the_recipient_to_employer(client, membership):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    advisor_membership = PrescriberMembershipFactory(organization__authorized=True)
    JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker,
        professional=advisor_membership.user,
        prescriber_organization=advisor_membership.organization,
        last_action_at=datetime.datetime(2025, 3, 10, tzinfo=datetime.UTC),
    )
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assertContains(
        response,
        f"""<p class="mb-0">
            Ce bilan sera envoyé à <strong>{advisor_membership.user.get_full_name()}</strong>,
            de {advisor_membership.organization.display_name}.
            Nous l’avons choisi car c’est le dernier prescripteur habilité à être intervenu
            pour {contract.job_seeker.get_full_name()} (en mars 2025).
        </p>""",
        html=True,
        count=1,
    )
    assertNotContains(response, NO_RECIPIENT)


@freeze_time("2026-01-15")
def test_create_pro_support_report_without_recipient_for_employer(client, mailoutbox, membership):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assertContains(response, f"{NO_RECIPIENT} {contract.job_seeker.get_full_name()}.")

    response = client.post(
        create_url(contract.job_seeker),
        data={"autonomy": "3", "has_solution": "True", "solution": ProSupportReportSolution.TRAINING},
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.SUCCESS, "Bilan enregistré dans le dossier du salarié. Il n’a été envoyé à personne."
            )
        ],
    )
    report = ProSupportReport.objects.get()
    assert report.notified_prescriber is None
    assert report.notified_prescriber_organization is None
    assert report.notified_prescriber_source == ""
    assert mailoutbox == []


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


def member_of_the_notified_organization(report, authorized=True):
    organization = PrescriberOrganizationFactory(with_membership=True, authorized=authorized)
    ProSupportReport.objects.filter(pk=report.pk).update(notified_prescriber_organization=organization)
    return organization.members.get()


@pytest.mark.parametrize(
    "user_factory,status_code",
    [
        (lambda report: advisor_organization(report).members.get(), 200),
        (lambda report: advisor_organization(report, ended=True).members.get(), 200),
        (lambda report: PrescriberMembershipFactory(organization=advisor_organization(report)).user, 200),
        (lambda report: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(), 404),
        (lambda report: advisor_organization(report, authorized=False).members.get(), 404),
        (advisor_who_created_the_job_seeker, 404),
        (member_of_the_notified_organization, 200),
        (lambda report: member_of_the_notified_organization(report, authorized=False), 404),
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
        "member_of_the_notified_organization",
        "member_of_the_notified_organization_no_longer_authorized",
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


def test_pro_support_report_offers_the_notified_prescriber_to_switch_organization(client):
    report = ProSupportReportFactory()
    notified_organization = advisor_organization(report)
    prescriber = notified_organization.members.get()
    ProSupportReport.objects.filter(pk=report.pk).update(
        notified_prescriber=prescriber, notified_prescriber_organization=notified_organization
    )
    other_organization = PrescriberMembershipFactory(user=prescriber, organization__authorized=True).organization
    client.force_login(prescriber)
    client.post(
        reverse("dashboard:switch_organization"), {"organization_key": other_organization.organization_switch_key}
    )

    response = client.get(report_url(report))
    assertContains(
        response,
        f"Ce bilan a été envoyé à la structure {notified_organization.display_name}. "
        "Connectez-vous à cette structure pour le consulter.",
    )
    assertContains(response, SWITCH_ORGANIZATION)
    assertNotContains(response, report.job_seeker.get_full_name())

    response = client.post(
        reverse("dashboard:switch_organization", query={"next_url": report_url(report)}),
        {"organization_key": notified_organization.organization_switch_key},
    )
    assertRedirects(response, report_url(report), fetch_redirect_response=False)
    response = client.get(report_url(report))
    assertContains(
        response, f"<h1>Bilan d’accompagnement de {report.job_seeker.get_inverted_full_name()}</h1>", html=True
    )
    assertNotContains(response, SWITCH_ORGANIZATION)


def report_notified_before_organizations(prescriber, organization):
    return ProSupportReportFactory(notified_prescriber=prescriber)


def report_notified_to_an_organization(prescriber, organization):
    return ProSupportReportFactory(notified_prescriber=prescriber, notified_prescriber_organization=organization)


@pytest.mark.parametrize(
    "report_factory,user_factory,switch_to_another_organization",
    [
        (report_notified_before_organizations, lambda prescriber: prescriber, True),
        (report_notified_to_an_organization, lambda prescriber: PrescriberFactory(), True),
        # No endless offer to switch to the current organization.
        (report_notified_to_an_organization, lambda prescriber: prescriber, False),
    ],
    ids=["report_before_organizations", "not_a_member", "current_organization_no_longer_authorized"],
)
def test_pro_support_report_not_found_for_a_prescriber_of_another_organization(
    client, report_factory, user_factory, switch_to_another_organization
):
    # Not authorized (anymore): the notified organization cannot view the report.
    membership = PrescriberMembershipFactory()
    report = report_factory(membership.user, membership.organization)
    user = user_factory(membership.user)
    client.force_login(user)
    if switch_to_another_organization:
        other_organization = PrescriberMembershipFactory(user=user, organization__authorized=True).organization
        client.post(
            reverse("dashboard:switch_organization"), {"organization_key": other_organization.organization_switch_key}
        )

    response = client.get(report_url(report))
    assert response.status_code == 404


class TestXpRefIae:
    @pytest.fixture(autouse=True)
    def setup_experiment(self, settings):
        settings.XP_REF_IAE_DEPARTMENTS = {"06": ["06"], "83": ["83", "84"]}
        settings.XP_REF_IAE_END_DATE = timezone.localdate()

    def login_ft_agent(self, client, settings, department="83"):
        membership = PrescriberMembershipFactory(
            organization__france_travail=True, organization__department=department
        )
        settings.XP_REF_IAE_USER_PKS = [membership.user.pk]
        client.force_login(membership.user)

    @pytest.mark.parametrize(
        "agency_department,company_department,status_code",
        [("06", "06", 200), ("83", "84", 200), ("83", "06", 404), ("13", "13", 404)],
        ids=["own_department", "associated_department", "other_department", "department_outside_experiment"],
    )
    def test_access(self, client, settings, agency_department, company_department, status_code):
        report = ProSupportReportFactory(contract__company__department=company_department)
        self.login_ft_agent(client, settings, department=agency_department)
        assert client.get(report_url(report)).status_code == status_code

    def test_no_access_for_an_agent_who_is_not_a_tester(self, client, settings):
        report = ProSupportReportFactory(contract__company__department="83")
        self.login_ft_agent(client, settings)
        settings.XP_REF_IAE_USER_PKS = []
        assert client.get(report_url(report)).status_code == 404

    def test_no_access_to_a_report_of_a_deleted_company(self, client, settings):
        report = ProSupportReportFactory(contract__company__department="83")
        ProSupportReport.objects.filter(pk=report.pk).update(company=None)
        self.login_ft_agent(client, settings)
        assert client.get(report_url(report)).status_code == 404

    def test_banner_on_job_seeker_card(self, client, settings):
        report = ProSupportReportFactory(contract__company__department="84")
        details_url = reverse("job_seekers_views:details", kwargs={"public_id": report.job_seeker.public_id})
        report_link = f'href="{report_url(report)}?back_url={details_url}"'

        self.login_ft_agent(client, settings)
        assertContains(client.get(details_url), report_link)

        settings.XP_REF_IAE_USER_PKS = []
        assertNotContains(client.get(details_url), report_link)


def introduction_url(report):
    return reverse("job_seekers_views:send_pro_support_report_introduction", kwargs={"public_id": report.public_id})


class TestSendProSupportReportIntroduction:
    @freeze_time("2026-01-15 10:00")
    def test_send(self, client, mailoutbox):
        report = ProSupportReportFactory()
        organization = advisor_organization(report)
        prescriber = PrescriberMembershipFactory(organization=organization, user__phone="").user
        client.force_login(prescriber)

        response = client.get(report_url(report))
        assertNotContains(response, "a quitté la structure")
        assertContains(response, f"Échanger avec {report.author.get_full_name()}")
        assertContains(response, f"Mise en relation avec {report.author.get_full_name()}")

        response = client.post(introduction_url(report), {"phone": "06 12 34 56 78"}, headers={"HX-Request": "true"})
        assert response.headers["HX-Refresh"] == "true"
        prescriber.refresh_from_db()
        assert prescriber.phone == "06 12 34 56 78"
        report.refresh_from_db()
        assert report.introduction_email_sent_at == timezone.now()
        assert report.introduction_email_recipient == report.author
        [email] = mailoutbox
        assert email.to == [report.author.email]
        assert email.cc == [prescriber.email]

        response = client.get(report_url(report))
        assertContains(response, "E-mail de mise en relation envoyé")
        assertContains(response, f"vous pouvez contacter {report.author.get_full_name()} dès maintenant")
        assertContains(response, f"Échanger de vive voix avec {report.author.get_full_name()}")
        assertNotContains(response, f"Échanger avec {report.author.get_full_name()}")

        # Any authorized prescriber who reads the report sees the contact details.
        client.force_login(PrescriberMembershipFactory(organization=organization).user)
        response = client.get(report_url(report))
        assertContains(response, f"Échanger de vive voix avec {report.author.get_full_name()}")
        assertNotContains(response, f"Échanger avec {report.author.get_full_name()}")

        # The SIAE does not see the contact details given to the prescriber.
        client.force_login(CompanyMembershipFactory(company=report.company, is_admin=False).user)
        response = client.get(report_url(report))
        assertNotContains(response, "Échanger de vive voix")
        assertNotContains(response, "Échanger avec")

    def test_missing_phone(self, client, mailoutbox):
        report = ProSupportReportFactory()
        client.force_login(PrescriberMembershipFactory(organization=advisor_organization(report), user__phone="").user)

        response = client.post(introduction_url(report), {"phone": ""}, headers={"HX-Request": "true"})
        assertContains(response, "Renseignez votre téléphone professionnel.")
        assert mailoutbox == []
        report.refresh_from_db()
        assert report.introduction_email_sent_at is None

    def test_already_sent(self, client, mailoutbox):
        report = ProSupportReportFactory(introduction_email_sent_at=timezone.now())
        client.force_login(advisor_organization(report).members.get())

        response = client.post(introduction_url(report), {"phone": "06 12 34 56 78"})
        assert response.status_code == 404
        assert mailoutbox == []

    def test_author_left(self, client, mailoutbox):
        report = ProSupportReportFactory(author__membership=False)
        admin = CompanyMembershipFactory(company=report.company).user
        client.force_login(advisor_organization(report).members.get())

        response = client.get(report_url(report))
        # The admin is unknown to the prescriber: the author's departure explains why they get the email.
        assertContains(response, f"par {report.author.get_full_name()} (a quitté la structure)")
        assertContains(response, "<span>Échanger avec l’employeur</span>", html=True)
        assertNotContains(response, f"Échanger avec {admin.get_full_name()}")
        assertContains(response, f"Mise en relation avec {report.company.display_name}")
        assertContains(
            response, f"L’e-mail de mise en relation sera envoyé à {admin.get_full_name()}, qui administre le compte"
        )

        client.post(introduction_url(report), {"phone": "06 12 34 56 78"}, headers={"HX-Request": "true"})
        [email] = mailoutbox
        assert email.to == [admin.email]
        report.refresh_from_db()
        assert report.introduction_email_recipient == admin

        response = client.get(report_url(report))
        assertContains(
            response, f"contacter {admin.get_full_name()}, qui administre le compte de la structure, dès maintenant"
        )
        assertContains(response, f"Échanger de vive voix avec {admin.get_full_name()}")

        # The contact details stay those of the admin who received the email.
        other_admin = CompanyMembershipFactory(company=report.company, user__last_login=timezone.now()).user
        response = client.get(report_url(report))
        assertContains(response, f"Échanger de vive voix avec {admin.get_full_name()}")
        assertNotContains(response, other_admin.get_full_name())

    @pytest.mark.parametrize(
        "report_factory",
        [
            lambda: ProSupportReportFactory(company=None),
            # The author is not a member of the company, which has no admin left.
            lambda: ProSupportReportFactory(author__membership=False),
        ],
        ids=["company_deleted", "author_left_without_admin"],
    )
    def test_without_contact(self, client, mailoutbox, report_factory):
        report = report_factory()
        client.force_login(advisor_organization(report).members.get())

        response = client.get(report_url(report))
        assertContains(response, '<h2 class="h3 mb-0">Contenu du bilan</h2>', html=True)
        assertNotContains(response, "Échanger avec")

        response = client.post(introduction_url(report), {"phone": "06 12 34 56 78"})
        assert response.status_code == 404
        assert mailoutbox == []

    @pytest.mark.parametrize(
        "user_factory,status_code",
        [
            (lambda report: CompanyMembershipFactory(company=report.company, is_admin=False).user, 403),
            (lambda report: advisor_organization(report, authorized=False).members.get(), 403),
            (lambda report: PrescriberOrganizationFactory(with_membership=True, authorized=True).members.get(), 404),
        ],
        ids=["employer_of_the_report", "prescriber_advisor_not_authorized", "authorized_prescriber_not_advisor"],
    )
    def test_access(self, client, mailoutbox, user_factory, status_code):
        report = ProSupportReportFactory()
        client.force_login(user_factory(report))

        response = client.post(introduction_url(report), {"phone": "06 12 34 56 78"})
        assert response.status_code == status_code
        assert mailoutbox == []
        report.refresh_from_db()
        assert report.introduction_email_sent_at is None


def first_read_url(report):
    return reverse("job_seekers_views:record_pro_support_report_first_read", kwargs={"public_id": report.public_id})


class TestRecordProSupportReportFirstRead:
    @freeze_time("2026-01-15 10:00")
    def test_record(self, client):
        report = ProSupportReportFactory()
        report.notified_prescriber = advisor_organization(report).members.get()
        report.save(update_fields=["notified_prescriber"])
        client.force_login(report.notified_prescriber)

        response = client.get(report_url(report))
        assertContains(response, f'hx-post="{first_read_url(report)}"')
        report.refresh_from_db()
        assert report.first_read_at is None

        client.post(first_read_url(report))
        report.refresh_from_db()
        assert report.first_read_at == timezone.now()

        response = client.get(report_url(report))
        assertNotContains(response, first_read_url(report))

    def test_already_read(self, client):
        report = ProSupportReportFactory(first_read_at=timezone.now() - datetime.timedelta(days=1))
        report.notified_prescriber = advisor_organization(report).members.get()
        report.save(update_fields=["notified_prescriber"])
        client.force_login(report.notified_prescriber)

        response = client.post(first_read_url(report))
        assert response.status_code == 200
        assert ProSupportReport.objects.get().first_read_at == report.first_read_at

    @pytest.mark.parametrize(
        "user_factory,status_code",
        [
            (lambda report, organization: PrescriberMembershipFactory(organization=organization).user, 200),
            (lambda report, organization: CompanyMembershipFactory(company=report.company).user, 403),
        ],
        ids=["coworker_of_the_recipient", "employer_of_the_report"],
    )
    def test_read_by_someone_else(self, client, user_factory, status_code):
        report = ProSupportReportFactory()
        organization = advisor_organization(report)
        report.notified_prescriber = organization.members.get()
        report.save(update_fields=["notified_prescriber"])
        client.force_login(user_factory(report, organization))

        response = client.get(report_url(report))
        assertNotContains(response, first_read_url(report))

        response = client.post(first_read_url(report))
        assert response.status_code == status_code
        report.refresh_from_db()
        assert report.first_read_at is None
