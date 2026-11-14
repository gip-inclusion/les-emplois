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
from tests.utils.testing import parse_response_to_soup, pretty_indented


NO_RECIPIENT = "Aucun prescripteur habilité n’est rattaché à"
RECIPIENT_BLOCK = "#pro-support-report-recipient"
REPORT_DATA = {"autonomy": "3", "has_solution": "True", "solution": ProSupportReportSolution.TRAINING}
UNKNOWN_AUTHORIZED_PRESCRIBER = "Cet utilisateur n’est pas inscrit en tant que prescripteur habilité"
SWITCH_ORGANIZATION = "Me connecter à cette structure"


@pytest.fixture
def membership():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True)


def end_of_journey_contract(company, end_date, **kwargs):
    contract = ContractFactory(
        company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date, **kwargs
    )
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
            # Only offered when no authorized prescriber is suggested.
            "no_known_prescriber": "on",
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

    # Sent reports cannot be modified.
    response = client.get(create_url(contract.job_seeker))
    assert response.status_code == 404


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "last_action_kind,reason",
    [
        (ActionKind.APPLY, "qui a envoyé une candidature pour {job_seeker} en mars 2025."),
        (ActionKind.IAE_ELIGIBILITY, "qui a validé l’éligibilité IAE de {job_seeker} en mars 2025."),
        (ActionKind.CREATE, "qui a créé le compte de {job_seeker} en mars 2025."),
        (ActionKind.SELF_ASSIGN, "qui s’est déclaré accompagnateur de {job_seeker} en mars 2025."),
        (ActionKind.GEIQ_ELIGIBILITY, "qui a validé l’éligibilité GEIQ de {job_seeker} en mars 2025."),
        (ActionKind.ORIENT, "qui a orienté {job_seeker} vers un service en mars 2025."),
    ],
    ids=["apply", "iae_eligibility", "create", "self_assign", "geiq_eligibility", "orient"],
)
def test_create_pro_support_report_shows_the_recipient_to_employer(client, membership, last_action_kind, reason):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    advisor_membership = PrescriberMembershipFactory(organization__authorized=True)
    JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker,
        professional=advisor_membership.user,
        prescriber_organization=advisor_membership.organization,
        last_action_kind=last_action_kind,
        last_action_at=datetime.datetime(2025, 3, 10, tzinfo=datetime.UTC),
    )
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assertContains(
        response,
        f"""<p class="mb-0">
            Ce bilan sera envoyé à <strong>{advisor_membership.user.get_full_name()}</strong>,
            de {advisor_membership.organization.display_name},
            {reason.format(job_seeker=contract.job_seeker.get_full_name())}
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

    # Notifying nobody is an explicit choice.
    response = client.post(create_url(contract.job_seeker), data=REPORT_DATA)
    assert response.context["form"].errors == {
        "no_known_prescriber": ["Indiquez l’adresse e-mail d’un prescripteur habilité ou cochez cette case."]
    }
    assert not ProSupportReport.objects.exists()

    # Displayed again with the box checked, the email stays aside and the report is only saved.
    response = client.post(create_url(contract.job_seeker), data={"no_known_prescriber": "on"})
    assert parse_response_to_soup(response, selector="#id_prescriber_email").has_attr("disabled")
    save_buttons = parse_response_to_soup(response, selector='[data-emplois-elements-visibility-on-selection="shown"]')
    assert "d-none" not in save_buttons.get("class", [])

    # The box prevails over an email left in the field.
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    response = client.post(
        create_url(contract.job_seeker),
        data=REPORT_DATA | {"no_known_prescriber": "on", "prescriber_email": prescriber.email},
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
def test_create_pro_support_report_recipient_block(client, snapshot, membership):
    contract = end_of_journey_contract(
        membership.company,
        timezone.localdate() + datetime.timedelta(days=10),
        job_seeker__for_snapshot=True,
    )
    client.force_login(membership.user)

    response = client.get(create_url(contract.job_seeker))
    assert pretty_indented(parse_response_to_soup(response, selector=RECIPIENT_BLOCK)) == snapshot(
        name="without_suggestion"
    )

    advisor = PrescriberFactory(
        for_snapshot=True, membership__organization__for_snapshot=True, membership__organization__authorized=True
    )
    JobSeekerAssignmentFactory(
        job_seeker=contract.job_seeker,
        professional=advisor,
        prescriber_organization=advisor.prescriberorganization_set.get(),
        last_action_kind=ActionKind.APPLY,
        last_action_at=datetime.datetime(2025, 3, 10, tzinfo=datetime.UTC),
    )
    response = client.get(create_url(contract.job_seeker))
    assert pretty_indented(parse_response_to_soup(response, selector=RECIPIENT_BLOCK)) == snapshot(
        name="with_suggestion"
    )


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "with_suggestion,choose_the_suggestion,source",
    [
        (True, False, ProSupportReportRecipientSource.CHOSEN),
        (True, True, ProSupportReportRecipientSource.SUGGESTED),
        (False, False, ProSupportReportRecipientSource.ADDED),
    ],
    ids=["another_prescriber", "the_suggested_prescriber", "without_suggestion"],
)
def test_create_pro_support_report_for_a_prescriber_chosen_by_employer(
    client, mailoutbox, membership, with_suggestion, choose_the_suggestion, source
):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    suggested_membership = PrescriberMembershipFactory(organization__authorized=True)
    if with_suggestion:
        JobSeekerAssignmentFactory(
            job_seeker=contract.job_seeker,
            professional=suggested_membership.user,
            prescriber_organization=suggested_membership.organization,
        )
    if choose_the_suggestion:
        chosen_membership = suggested_membership
    else:
        chosen_membership = PrescriberMembershipFactory(organization__authorized=True)
    client.force_login(membership.user)

    response = client.post(
        create_url(contract.job_seeker), data=REPORT_DATA | {"prescriber_email": chosen_membership.user.email}
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.SUCCESS,
                f"Bilan envoyé à {chosen_membership.user.get_full_name()}, "
                f"de {chosen_membership.organization.display_name}",
            )
        ],
    )
    report = ProSupportReport.objects.get()
    assert report.notified_prescriber == chosen_membership.user
    assert report.notified_prescriber_organization == chosen_membership.organization
    assert report.notified_prescriber_source == source
    # The suggested prescriber is not notified when another one is chosen.
    assert [email.to for email in mailoutbox] == [[chosen_membership.user.email]]


def prescriber_who_left_the_authorized_organization():
    membership = PrescriberMembershipFactory(organization__authorized=True, is_active=False)
    # A coworker remains an active member.
    PrescriberMembershipFactory(organization=membership.organization)
    return membership.user


@freeze_time("2026-01-15")
@pytest.mark.parametrize(
    "email_factory",
    [
        lambda: "inconnu@example.com",
        lambda: PrescriberFactory(membership__organization__authorized=False).email,
        lambda: prescriber_who_left_the_authorized_organization().email,
        lambda: PrescriberFactory(membership__organization__authorized=True, is_active=False).email,
        lambda: CompanyMembershipFactory().user.email,
    ],
    ids=["unknown", "prescriber_not_authorized", "prescriber_who_left", "inactive_prescriber", "employer"],
)
def test_create_pro_support_report_for_an_unknown_authorized_prescriber(client, membership, email_factory):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    client.force_login(membership.user)

    response = client.post(create_url(contract.job_seeker), data=REPORT_DATA | {"prescriber_email": email_factory()})
    assertContains(response, UNKNOWN_AUTHORIZED_PRESCRIBER)
    assert not ProSupportReport.objects.exists()


@freeze_time("2026-01-15")
def test_create_pro_support_report_for_a_prescriber_of_several_organizations(client, mailoutbox, membership):
    contract = end_of_journey_contract(membership.company, timezone.localdate() + datetime.timedelta(days=10))
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    other_organization = PrescriberMembershipFactory(user=prescriber, organization__authorized=True).organization
    client.force_login(membership.user)

    # The organization is asked for, even if the email was not checked beforehand.
    data = REPORT_DATA | {"prescriber_email": prescriber.email}
    response = client.post(create_url(contract.job_seeker), data=data)
    assert response.context["form"].errors == {"prescriber_organization": ["Ce champ est obligatoire."]}
    assertContains(response, f"Organisation de {prescriber.get_full_name()} qui recevra le bilan")

    # The employer cannot open the report to an organization the prescriber is not a member of.
    forged_organization = PrescriberOrganizationFactory(authorized=True)
    response = client.post(
        create_url(contract.job_seeker), data=data | {"prescriber_organization": forged_organization.pk}
    )
    assert response.context["form"].errors == {
        "prescriber_organization": ["Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."]
    }
    assert not ProSupportReport.objects.exists()

    client.post(create_url(contract.job_seeker), data=data | {"prescriber_organization": other_organization.pk})
    report = ProSupportReport.objects.get()
    assert report.notified_prescriber == prescriber
    assert report.notified_prescriber_organization == other_organization
    assert [email.to for email in mailoutbox] == [[prescriber.email]]


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
