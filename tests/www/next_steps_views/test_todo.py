import datetime
import types

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationRequestStatus
from itou.job_applications.enums import JobApplicationState
from itou.www.next_steps_views.actions import Group, Kind, describe_job_seekers, elapsed_display
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory, ProSupportReportFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


TODO_URL = reverse("next_steps_views:todo")
NBSP = "\u00a0"


def journey_url(kind, pk):
    return reverse("next_steps_views:journey", kwargs={"kind": kind, "pk": pk})


NAV_LINK = f'href="{TODO_URL}"'


@pytest.fixture(autouse=True)
def experiment_off(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = False
    settings.NEXT_STEPS_USER_PKS = []
    settings.NEXT_STEPS_COMPANY_PKS = []
    settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS = []


@pytest.fixture
def employer_membership():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True)


@pytest.fixture
def prescriber_membership():
    return PrescriberMembershipFactory(organization__authorized=True)


def actions_of(response):
    return [action for group in response.context["groups"] for action in group["actions"]]


def summary(response):
    return [(action.group, action.kind, action.job_seeker) for action in actions_of(response)]


# Access
# ------------------------------------------------------------------------------


def test_off_by_default(client, employer_membership, prescriber_membership):
    for user in [employer_membership.user, prescriber_membership.user]:
        client.force_login(user)
        assert client.get(TODO_URL).status_code == 404
        assertNotContains(client.get(reverse("dashboard:index")), NAV_LINK)


@pytest.mark.parametrize(
    "enable",
    [
        lambda settings, membership: setattr(settings, "NEXT_STEPS_FOR_EVERYONE", True),
        lambda settings, membership: setattr(settings, "NEXT_STEPS_USER_PKS", [membership.user.pk]),
        lambda settings, membership: setattr(settings, "NEXT_STEPS_COMPANY_PKS", [membership.company.pk]),
    ],
    ids=["everyone", "user", "company"],
)
def test_enabled_for_employer(client, settings, employer_membership, enable):
    enable(settings, employer_membership)
    client.force_login(employer_membership.user)
    assertContains(client.get(TODO_URL), "Rien ne vous attend")
    assertContains(client.get(reverse("dashboard:index")), NAV_LINK)


@pytest.mark.parametrize(
    "enable",
    [
        lambda settings, membership: setattr(settings, "NEXT_STEPS_USER_PKS", [membership.user.pk]),
        lambda settings, membership: setattr(
            settings, "NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS", [membership.organization.pk]
        ),
    ],
    ids=["user", "organization"],
)
def test_enabled_for_prescriber(client, settings, prescriber_membership, enable):
    enable(settings, prescriber_membership)
    client.force_login(prescriber_membership.user)
    assert client.get(TODO_URL).status_code == 200


def test_a_listed_organization_pk_only_enables_its_own_kind(client, settings, employer_membership):
    # Companies and prescriber organizations have separate pk sequences.
    settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS = [employer_membership.company.pk]
    client.force_login(employer_membership.user)
    assert client.get(TODO_URL).status_code == 404


def test_other_members_of_the_organization_are_left_out(client, settings, employer_membership):
    settings.NEXT_STEPS_USER_PKS = [employer_membership.user.pk]
    colleague = CompanyMembershipFactory(company=employer_membership.company).user
    client.force_login(colleague)
    assert client.get(TODO_URL).status_code == 404


def test_job_seekers_are_left_out(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    client.force_login(JobSeekerFactory())
    assert client.get(TODO_URL).status_code == 404


# Employer actions
# ------------------------------------------------------------------------------


@pytest.fixture
def employer_client(client, settings, employer_membership):
    settings.NEXT_STEPS_COMPANY_PKS = [employer_membership.company.pk]
    client.force_login(employer_membership.user)
    return client


def ended_contract(company, days_ago=10):
    end_date = timezone.localdate() - datetime.timedelta(days=days_ago)
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    JobApplicationFactory(
        job_seeker=contract.job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
    )
    return contract


def test_employer_new_job_application(employer_client, employer_membership):
    job_application = JobApplicationFactory(
        to_company=employer_membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    # Neither processed nor archived applications are expected actions.
    JobApplicationFactory(
        to_company=employer_membership.company,
        state=JobApplicationState.PROCESSING,
        sent_by_authorized_prescriber=True,
    )
    JobApplicationFactory(
        to_company=employer_membership.company,
        state=JobApplicationState.NEW,
        sent_by_authorized_prescriber=True,
        archived_at=timezone.now(),
    )

    response = employer_client.get(TODO_URL)
    # Due within a week: this week's.
    assert summary(response) == [(Group.WEEK, Kind.JOB_APPLICATION, job_application.job_seeker)]
    # How long it has waited, rather than its due date.
    assertContains(response, "En attente de réponse depuis aujourd’hui")
    assertContains(response, "1 action vous attend")
    assertContains(response, "Répondre à sa candidature")
    assertContains(response, journey_url("candidature", job_application.pk))


def test_employer_ended_contract(employer_client, employer_membership):
    contract = ended_contract(employer_membership.company)
    job_seeker = contract.job_seeker

    response = employer_client.get(TODO_URL)
    # The suspension is due a week after the contract's end, the report a month after it.
    assert summary(response) == [
        (Group.LATE, Kind.APPROVAL_SUSPENSION, job_seeker),
        (Group.WATCH, Kind.PRO_SUPPORT_REPORT_FILL, job_seeker),
    ]
    assertContains(response, f"En retard de 3{NBSP}jours")
    assertContains(response, f"Le contrat est terminé depuis le {contract.end_date:%d/%m/%Y}")
    assertContains(response, journey_url("suspension", job_seeker.approvals.get().pk))
    assertContains(response, journey_url("bilan", job_seeker.public_id))

    # Once the report is filled, only the suspension remains.
    ProSupportReportFactory(contract=contract)
    assert summary(employer_client.get(TODO_URL)) == [(Group.LATE, Kind.APPROVAL_SUSPENSION, job_seeker)]


def test_employer_contract_ending_soon(employer_client, employer_membership):
    end_date = timezone.localdate() + datetime.timedelta(days=10)
    contract = ContractFactory(company=employer_membership.company, end_date=end_date)
    ApprovalFactory(user=contract.job_seeker)

    response = employer_client.get(TODO_URL)
    assert summary(response) == [(Group.WATCH, Kind.PRO_SUPPORT_REPORT_FILL, contract.job_seeker)]
    # Only the actions due within a week are counted.
    assertContains(response, "Rien ne vous attend")


def test_employer_contract_ended_elsewhere_is_not_theirs(employer_client, employer_membership):
    contract = ended_contract(employer_membership.company)
    # Hired by another company since: that company handles the end of the contract.
    ContractFactory(job_seeker=contract.job_seeker, start_date=timezone.localdate(), end_date=None)
    assert summary(employer_client.get(TODO_URL)) == []


def test_employer_prolongation_request_waiting_for_decision(employer_client, employer_membership):
    prolongation_request = ProlongationRequestFactory(declared_by_siae=employer_membership.company)
    ProlongationRequestFactory(
        declared_by_siae=employer_membership.company, status=ProlongationRequestStatus.GRANTED, processed=True
    )

    response = employer_client.get(TODO_URL)
    assert summary(response) == [(Group.WATCH, Kind.WAITING, prolongation_request.approval.user)]
    assertContains(response, ProlongationRequestStatus.PENDING.label)
    assertContains(response, prolongation_request.assigned_to.get_full_name())


# Prescriber actions
# ------------------------------------------------------------------------------


@pytest.fixture
def prescriber_client(client, settings, prescriber_membership):
    settings.NEXT_STEPS_PRESCRIBER_ORGANIZATION_PKS = [prescriber_membership.organization.pk]
    client.force_login(prescriber_membership.user)
    return client


def assign(job_seeker, membership):
    JobSeekerAssignmentFactory(
        job_seeker=job_seeker, professional=membership.user, prescriber_organization=membership.organization
    )


def test_prescriber_prolongation_request(prescriber_client, prescriber_membership):
    prolongation_request = ProlongationRequestFactory(
        prescriber_organization=prescriber_membership.organization,
        assigned_to=prescriber_membership.user,
        approval__end_at=timezone.localdate() + datetime.timedelta(days=3),
    )
    # Assigned to a colleague.
    ProlongationRequestFactory(
        prescriber_organization=prescriber_membership.organization,
        assigned_to=PrescriberMembershipFactory(organization=prescriber_membership.organization).user,
    )

    response = prescriber_client.get(TODO_URL)
    # Due 10 days after it was asked, as the platform's reminder, but the PASS IAE ends in 3 days.
    assert summary(response) == [(Group.WEEK, Kind.PROLONGATION_REQUEST, prolongation_request.approval.user)]
    assert [action.due for action in actions_of(response)] == [prolongation_request.approval.end_at]
    assertContains(
        response,
        journey_url("prolongation", prolongation_request.pk),
    )


def test_prescriber_pro_support_report_to_request_then_to_read(prescriber_client, prescriber_membership):
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(end_date=end_date, start_date=end_date - datetime.timedelta(days=200))
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    assign(contract.job_seeker, prescriber_membership)
    # Not followed by this prescriber.
    other_contract = ContractFactory(end_date=end_date, start_date=end_date - datetime.timedelta(days=200))
    ApprovalFactory(user=other_contract.job_seeker, start_at=other_contract.start_date)

    response = prescriber_client.get(TODO_URL)
    # Due when the SIAE's report is, a month after the contract's end.
    assert summary(response) == [(Group.WATCH, Kind.PRO_SUPPORT_REPORT_REQUEST, contract.job_seeker)]
    # The prescriber asks for the report from the job seeker's page: only the SIAE fills it.
    assertContains(response, "C’est la SIAE qui remplit le bilan.")
    assertNotContains(response, "pro-support-report/create")

    ProSupportReportFactory(contract=contract)
    response = prescriber_client.get(TODO_URL)
    assert summary(response) == [(Group.WEEK, Kind.PRO_SUPPORT_REPORT_READ, contract.job_seeker)]


def test_prescriber_eligibility_to_validate(prescriber_client, prescriber_membership):
    job_application = JobApplicationFactory(
        state=JobApplicationState.NEW, sent_by_authorized_prescriber=True, to_company__subject_to_iae_rules=True
    )
    job_seeker = job_application.job_seeker
    assign(job_seeker, prescriber_membership)

    response = prescriber_client.get(TODO_URL)
    assert summary(response) == [(Group.WEEK, Kind.ELIGIBILITY, job_seeker)]
    assertContains(response, journey_url("eligibilite", job_seeker.public_id))

    IAEEligibilityDiagnosisFactory(job_seeker=job_seeker, from_prescriber=True)
    assert summary(prescriber_client.get(TODO_URL)) == []


# Order
# ------------------------------------------------------------------------------


def test_job_applications_do_not_hide_the_rarer_actions(employer_client, employer_membership):
    company = employer_membership.company
    received = timezone.now() - datetime.timedelta(days=20)
    job_applications = [
        JobApplicationFactory(
            to_company=company,
            state=JobApplicationState.NEW,
            sent_by_authorized_prescriber=True,
            created_at=received + datetime.timedelta(hours=hours),
        )
        for hours in range(5)
    ]
    contract = ended_contract(company)

    response = employer_client.get(TODO_URL)
    [late, *_] = response.context["groups"]
    # All late, the nearest due date first: the job applications were due 13 days ago, the suspension 3 days ago.
    # Beyond three job applications, the others are folded, and the suspension stays in sight.
    assert [(action.kind, action.job_seeker) for action in late["actions"]] == [
        (Kind.JOB_APPLICATION, job_applications[0].job_seeker),
        (Kind.JOB_APPLICATION, job_applications[1].job_seeker),
        (Kind.JOB_APPLICATION, job_applications[2].job_seeker),
        (Kind.APPROVAL_SUSPENSION, contract.job_seeker),
    ]
    assert [action.job_seeker for action in late["folded"]] == [
        job_applications[3].job_seeker,
        job_applications[4].job_seeker,
    ]
    assert late["count"] == 6
    assertContains(response, "Afficher 2 autres candidatures")
    assertContains(response, f"En attente de réponse depuis 2{NBSP}semaines", count=5)
    assertContains(response, "6 actions vous attendent")


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "aujourd’hui"),
        (1, f"1{NBSP}jour"),
        (13, f"13{NBSP}jours"),
        (14, f"2{NBSP}semaines"),
        (59, f"8{NBSP}semaines"),
        (60, f"1{NBSP}mois"),
        (474, f"15{NBSP}mois"),
    ],
)
@freeze_time("2026-11-17")
def test_elapsed_display(days, expected):
    assert elapsed_display(timezone.localdate() - datetime.timedelta(days=days)) == expected


def test_suspension_due_before_the_approval_ends(employer_client, employer_membership):
    company = employer_membership.company
    yesterday = timezone.localdate() - datetime.timedelta(days=1)
    contract = ContractFactory(
        company=company, start_date=yesterday - datetime.timedelta(days=200), end_date=yesterday
    )
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date, end_at=timezone.localdate())
    JobApplicationFactory(
        job_seeker=contract.job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
    )

    response = employer_client.get(TODO_URL)
    # A week after the contract's end, but the PASS IAE ends today: it cannot be suspended afterwards.
    assert summary(response)[0] == (Group.TODAY, Kind.APPROVAL_SUSPENSION, contract.job_seeker)
    assertContains(response, "À faire aujourd’hui")


def test_unauthorized_prescriber_has_no_iae_actions(client, settings):
    membership = PrescriberMembershipFactory(organization__authorized=False)
    settings.NEXT_STEPS_USER_PKS = [membership.user.pk]
    job_application = JobApplicationFactory(state=JobApplicationState.NEW, sent_by_prescriber=True)
    assign(job_application.job_seeker, membership)
    client.force_login(membership.user)

    response = client.get(TODO_URL)
    assert summary(response) == []
    assertContains(response, "Rien ne vous attend")


def test_actions_say_who_they_are_about(client, settings, employer_membership):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    job_seeker = JobSeekerFactory(
        city="Vénissieux", jobseeker_profile__birthdate=timezone.localdate() - datetime.timedelta(days=37 * 366)
    )
    JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=employer_membership.company,
        state=JobApplicationState.NEW,
        sent_by_authorized_prescriber=True,
    )
    client.force_login(employer_membership.user)

    response = client.get(TODO_URL)
    # As in the prototype: the name in tertiary blue, then the age and the city.
    assertContains(response, 'class="link-tertiary link-underline-opacity-0 link-underline-opacity-100-hover fw-bold"')
    assertContains(response, f"<span>{job_seeker.jobseeker_profile.age} ans · Vénissieux</span>", html=True)


def test_masked_job_seekers_show_no_age_nor_city():
    job_seeker = JobSeekerFactory(city="Vénissieux")
    action = types.SimpleNamespace(job_seeker=job_seeker)
    describe_job_seekers([action], lambda job_seeker: False)
    assert action.job_seeker_details == ""
    assert action.user_can_view_personal_information is False


def test_no_job_descriptions_reminder_on_the_experiment_pages(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = CompanyMembershipFactory(
        company__spontaneous_applications_open_since=timezone.now() - datetime.timedelta(days=61)
    )
    client.force_login(membership.user)

    assertNotContains(client.get(TODO_URL), "deactivation-job-banner")
    # Elsewhere, the reminder stays.
    assertContains(client.get(reverse("dashboard:index")), "deactivation-job-banner")


# Menu
# ------------------------------------------------------------------------------


def test_menu_counts_the_urgent_actions(employer_client, employer_membership):
    company = employer_membership.company
    # No urgent action yet: no badge, and the experiment no longer says « Beta ».
    response = employer_client.get(reverse("dashboard:index"))
    assertNotContains(response, "urgente")
    assertNotContains(response, "Beta")

    # Late, then due this week: only the first is urgent.
    JobApplicationFactory(
        to_company=company,
        state=JobApplicationState.NEW,
        sent_by_authorized_prescriber=True,
        created_at=timezone.now() - datetime.timedelta(days=20),
    )
    JobApplicationFactory(to_company=company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True)
    response = employer_client.get(reverse("dashboard:index"))
    assertContains(response, '<span class="visually-hidden">action urgente</span>', count=1)
