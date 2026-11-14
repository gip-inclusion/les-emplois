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
from tests.users.factories import ItouStaffFactory, JobSeekerAssignmentFactory, JobSeekerFactory


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


def introduction_url(report):
    return reverse("job_seekers_views:send_pro_support_report_introduction", kwargs={"public_id": report.public_id})


class TestSendProSupportReportIntroduction:
    @freeze_time("2026-01-15 10:00")
    def test_send(self, client, mailoutbox):
        report = ProSupportReportFactory()
        CompanyMembershipFactory(company=report.company, user=report.author)
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
        CompanyMembershipFactory(company=report.company, user=report.author)
        client.force_login(PrescriberMembershipFactory(organization=advisor_organization(report), user__phone="").user)

        response = client.post(introduction_url(report), {"phone": ""}, headers={"HX-Request": "true"})
        assertContains(response, "Renseignez votre téléphone professionnel.")
        assert mailoutbox == []
        report.refresh_from_db()
        assert report.introduction_email_sent_at is None

    def test_already_sent(self, client, mailoutbox):
        report = ProSupportReportFactory(introduction_email_sent_at=timezone.now())
        CompanyMembershipFactory(company=report.company, user=report.author)
        client.force_login(advisor_organization(report).members.get())

        response = client.post(introduction_url(report), {"phone": "06 12 34 56 78"})
        assert response.status_code == 404
        assert mailoutbox == []

    def test_author_left(self, client, mailoutbox):
        report = ProSupportReportFactory()
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
            ProSupportReportFactory,
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
        CompanyMembershipFactory(company=report.company, user=report.author)
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

    def test_read_by_the_support_team(self, client):
        report = ProSupportReportFactory()
        report.notified_prescriber = advisor_organization(report).members.get()
        report.save(update_fields=["notified_prescriber"])
        client.force_login(ItouStaffFactory(is_superuser=True))
        client.post(reverse("hijack:acquire"), {"user_pk": report.notified_prescriber.pk})

        response = client.post(first_read_url(report))
        assert response.status_code == 200
        report.refresh_from_db()
        assert report.first_read_at is None

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
