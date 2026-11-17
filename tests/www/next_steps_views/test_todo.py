import datetime
import types

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationRequestStatus
from itou.job_applications.enums import JobApplicationState
from itou.rdv_insertion.models import Participation
from itou.www.next_steps_views.actions import Group, Kind, describe_job_seekers
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory, ProSupportReportFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.rdv_insertion.factories import ParticipationFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


TODO_URL = reverse("next_steps_views:todo")


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
    assert summary(response) == [(Group.TODAY, Kind.JOB_APPLICATION, job_application.job_seeker)]
    assertContains(response, "1 action vous attend")
    assertContains(response, "Répondre à sa candidature")
    assertContains(response, journey_url("candidature", job_application.pk))


def test_employer_ended_contract(employer_client, employer_membership):
    contract = ended_contract(employer_membership.company)
    job_seeker = contract.job_seeker

    response = employer_client.get(TODO_URL)
    assert summary(response) == [
        (Group.TODAY, Kind.APPROVAL_SUSPENSION, job_seeker),
        (Group.WEEK, Kind.PRO_SUPPORT_REPORT_FILL, job_seeker),
    ]
    assertContains(response, f"Le contrat est terminé depuis le {contract.end_date:%d/%m/%Y}")
    assertContains(response, journey_url("suspension", job_seeker.approvals.get().pk))
    assertContains(response, journey_url("bilan", job_seeker.public_id))

    # Once the report is filled, only the suspension remains.
    ProSupportReportFactory(contract=contract)
    assert summary(employer_client.get(TODO_URL)) == [(Group.TODAY, Kind.APPROVAL_SUSPENSION, job_seeker)]


def test_employer_contract_ending_soon(employer_client, employer_membership):
    end_date = timezone.localdate() + datetime.timedelta(days=10)
    contract = ContractFactory(company=employer_membership.company, end_date=end_date)
    ApprovalFactory(user=contract.job_seeker)

    response = employer_client.get(TODO_URL)
    assert summary(response) == [(Group.WATCH, Kind.PRO_SUPPORT_REPORT_FILL, contract.job_seeker)]
    # Only the expected actions of today and this week are counted.
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


def test_employer_appointment_with_undetermined_status(employer_client, employer_membership):
    company = employer_membership.company
    now = timezone.now()
    participation = ParticipationFactory(
        status=Participation.Status.UNKNOWN,
        appointment__company=company,
        appointment__start_at=now - datetime.timedelta(days=2),
        appointment__canceled_at=None,
    )
    # Upcoming, already determined, too old or from another company: nothing to do.
    ParticipationFactory(
        status=Participation.Status.UNKNOWN,
        appointment__company=company,
        appointment__start_at=now + datetime.timedelta(days=2),
    )
    ParticipationFactory(
        status=Participation.Status.SEEN,
        appointment__company=company,
        appointment__start_at=now - datetime.timedelta(days=2),
    )
    ParticipationFactory(
        status=Participation.Status.UNKNOWN,
        appointment__company=company,
        appointment__start_at=now - datetime.timedelta(days=60),
    )
    ParticipationFactory(
        status=Participation.Status.UNKNOWN,
        appointment__start_at=now - datetime.timedelta(days=2),
    )

    response = employer_client.get(TODO_URL)
    assert summary(response) == [(Group.WEEK, Kind.APPOINTMENT, participation.job_seeker)]
    assertContains(response, Participation.Status.UNKNOWN.label)


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
        prescriber_organization=prescriber_membership.organization, assigned_to=prescriber_membership.user
    )
    # Assigned to a colleague.
    ProlongationRequestFactory(
        prescriber_organization=prescriber_membership.organization,
        assigned_to=PrescriberMembershipFactory(organization=prescriber_membership.organization).user,
    )

    response = prescriber_client.get(TODO_URL)
    assert summary(response) == [(Group.TODAY, Kind.PROLONGATION_REQUEST, prolongation_request.approval.user)]
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
    assert summary(response) == [(Group.WEEK, Kind.PRO_SUPPORT_REPORT_REQUEST, contract.job_seeker)]
    # The prescriber asks for the report from the job seeker's page: only the SIAE fills it.
    assertContains(response, "C’est la SIAE qui remplit le bilan.")
    assertNotContains(response, "pro-support-report/create")

    report = ProSupportReportFactory(contract=contract)
    response = prescriber_client.get(TODO_URL)
    assert summary(response) == [(Group.WEEK, Kind.PRO_SUPPORT_REPORT_READ, contract.job_seeker)]
    assertContains(response, reverse("job_seekers_views:pro_support_report", kwargs={"public_id": report.public_id}))


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
    assertContains(response, 'class="link-tertiary fw-bold"')
    assertContains(response, f"<span>{job_seeker.jobseeker_profile.age} ans · Vénissieux</span>", html=True)


def test_masked_job_seekers_show_no_age_nor_city():
    job_seeker = JobSeekerFactory(city="Vénissieux")
    action = types.SimpleNamespace(job_seeker=job_seeker)
    describe_job_seekers([action], lambda job_seeker: False)
    assert action.job_seeker_details == ""
    assert action.user_can_view_personal_information is False
