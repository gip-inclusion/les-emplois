import datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationRequestDenyReason
from itou.approvals.models import Suspension
from itou.companies.enums import CompanyKind, ProSupportReportBarrier
from itou.job_applications.enums import JobApplicationState, RefusalReason
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory


TODO_URL = reverse("next_steps_views:todo")


def test_the_button_opens_a_drawer_and_still_leads_to_the_form_without_javascript(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(membership.user)

    response = client.get(TODO_URL)
    action = response.context["groups"][0]["actions"][0]
    form_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    # The button keeps the form as its target, Bootstrap opens the drawer instead when JavaScript runs.
    assertContains(
        response,
        f'href="{form_url}?back_url={TODO_URL}"\n               data-bs-toggle="offcanvas" '
        f'data-bs-target="#{action.uid}"',
    )
    assertContains(response, f'<div class="offcanvas offcanvas-end" tabindex="-1" id="{action.uid}"')
    assertContains(response, "Ouvrir la candidature")
    assertContains(response, job_application.sender_prescriber_organization.display_name)
    # The refusal reasons the form offers to this kind of company.
    assertContains(response, RefusalReason.NO_POSITION.label)
    assertNotContains(response, RefusalReason.NON_ELIGIBLE.label)
    assertNotContains(response, RefusalReason.AUTO.label)


def test_suspension_journey(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = CompanyMembershipFactory(company__kind=CompanyKind.AI)
    company = membership.company
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    approval = ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    JobApplicationFactory(
        job_seeker=contract.job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
    )
    client.force_login(membership.user)

    response = client.get(TODO_URL)
    assertContains(response, approval.number_with_spaces)
    assertContains(response, Suspension.Reason.FINISHED_CONTRACT.label)
    # Only ACI and EI may use this reason.
    assertNotContains(response, Suspension.Reason.CONTRAT_PASSERELLE.label)
    # The report journey of the same person.
    assertContains(response, ProSupportReportBarrier.LITERACY.label)
    assertContains(response, "Une fois envoyé, il ne peut plus être modifié.")


def test_prolongation_request_journey(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = PrescriberMembershipFactory(organization__authorized=True)
    prolongation_request = ProlongationRequestFactory(
        prescriber_organization=membership.organization, assigned_to=membership.user
    )
    client.force_login(membership.user)

    response = client.get(TODO_URL)
    assertContains(response, escape(prolongation_request.get_reason_display()))
    assertContains(response, prolongation_request.declared_by_siae.display_name)
    for reason in ProlongationRequestDenyReason:
        assertContains(response, escape(reason.label))
    assertContains(response, "Ouvrir la demande")


def test_waiting_actions_have_no_drawer(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    ProlongationRequestFactory(declared_by_siae=membership.company)
    client.force_login(membership.user)

    response = client.get(TODO_URL)
    assert len(response.context["groups"][2]["actions"]) == 1
    assertNotContains(response, 'class="offcanvas offcanvas-end"')
