import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.models import Suspension
from itou.companies.enums import ProSupportReportBarrier
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.job_applications.enums import JobApplicationState
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyMembershipFactory, ContractFactory, ProSupportReportFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


@pytest.fixture(autouse=True)
def experiment_for_everyone(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True


NBSP = " "


def page_url(job_seeker):
    return reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id})


def fr_iso(date):
    return f"{date:%Y-%m-%d}"


def fr(date):
    return f"{date:%d/%m/%Y}"


def test_off_by_default(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = False
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    assert client.get(page_url(JobSeekerFactory())).status_code == 404


def test_only_job_seekers_have_a_page(client):
    membership = CompanyMembershipFactory()
    client.force_login(membership.user)
    assert client.get(page_url(membership.user)).status_code == 404


def test_employer_after_the_end_of_the_contract(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    job_seeker = contract.job_seeker
    approval = ApprovalFactory(user=job_seeker, start_at=contract.start_date)
    JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
    )
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=membership.user, company=company)
    advisor = JobSeekerAssignmentFactory(
        job_seeker=job_seeker, prescriber_organization=PrescriberMembershipFactory().organization
    ).professional
    client.force_login(membership.user)

    response = client.get(page_url(job_seeker))
    # Who follows the person, the signed-in professional first marked as such.
    assertContains(response, membership.user.get_full_name())
    assertContains(response, "· vous", count=1)
    assertContains(response, advisor.get_full_name())
    # Where the person stands.
    # The contract against the PASS IAE, said (the first of the layouts to compare): no sentence repeats it.
    assertContains(
        response, f"Terminé le {fr(end_date)}{NBSP}: 10{NBSP}jours de PASS{NBSP}IAE consommés depuis, sans contrat"
    )
    assertNotContains(response, "Son contrat chez vous")
    assertContains(response, "next-step-frise__block--pass")
    assertContains(response, f"<b>Aujourd’hui</b> · {fr(timezone.localdate())}")
    # The PASS IAE fills up to today, as a gauge, and says what is left of it.
    assertContains(response, 'style="--elapsed: ')
    assertContains(response, '<span class="fs-xs">Reste</span>')
    assertContains(response, f"Son PASS IAE est valide jusqu’au {fr(approval.end_at)}.")
    assertContains(response, "Ses jours continuent d’être décomptés tant qu’il n’est pas suspendu.")
    # What to do: the same actions as the queue, for this person only, without repeating their name.
    assertContains(response, "Suspendre le PASS IAE")
    assertContains(response, "Remplir le bilan d’accompagnement")
    assertNotContains(response, f'href="{page_url(job_seeker)}"')
    # The folded file leads to the existing tabs: PASS IAE, diagnosis, contracts, job applications, personal
    # information. Without any report, that part is a plain line, with nothing to open.
    assertContains(response, '<details class="next-step-file', count=5)
    assertContains(response, '<div class="d-flex align-items-center gap-3 px-3 px-md-4 py-3 border-top"', count=1)
    assertContains(response, reverse("next_steps_views:approval", kwargs={"public_id": job_seeker.public_id}))
    assertContains(response, reverse("job_seekers_views:contracts", kwargs={"public_id": job_seeker.public_id}))
    # Each summary line says enough to skip opening it.
    assertContains(response, f"Du {fr(approval.start_at)} au {fr(approval.end_at)}")
    assertContains(response, "1 contrat")
    assertContains(response, "1 candidature")
    assertContains(response, "Aucun bilan")


def test_suspended_approval(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    approval = ApprovalFactory(start_at=timezone.localdate() - datetime.timedelta(days=100))
    suspension = SuspensionFactory(
        approval=approval,
        start_at=timezone.localdate() - datetime.timedelta(days=5),
        end_at=timezone.localdate() + datetime.timedelta(days=30),
        reason=Suspension.Reason.FINISHED_CONTRACT,
    )
    client.force_login(membership.user)

    response = client.get(page_url(approval.user))
    assertContains(
        response,
        f"Son PASS IAE est suspendu depuis le {fr(suspension.start_at)}, jusqu’au {fr(suspension.end_at)}, "
        f"motif : {Suspension.Reason.FINISHED_CONTRACT.label}.",
    )


def test_authorized_prescriber_during_the_waiting_period(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    approval = ApprovalFactory(
        start_at=timezone.localdate() - datetime.timedelta(days=900),
        end_at=timezone.localdate() - datetime.timedelta(days=100),
        # Without the diagnosis the factory would create today, still valid.
        origin_ai_stock=True,
    )
    client.force_login(membership.user)

    response = client.get(page_url(approval.user))
    assertContains(response, f"Son PASS IAE a expiré le {fr(approval.end_at)}.")
    assertContains(
        response,
        f"Jusqu’au {fr(approval.waiting_period_end)}, seul un prescripteur habilité peut valider "
        "à nouveau son éligibilité.",
    )
    assertContains(response, "Aucun contrat en structure d’insertion connu.")
    assertContains(response, "Aucun diagnostic en cours de validité")


def test_unauthorized_prescriber_sees_no_more_than_on_the_job_seeker_page(client):
    membership = PrescriberMembershipFactory(organization__authorized=False)
    approval = ApprovalFactory()
    job_seeker = approval.user
    client.force_login(membership.user)

    response = client.get(page_url(job_seeker))
    # Like on the job seeker's page: the PASS IAE, but no contract.
    assertContains(response, f"Son PASS IAE est valide jusqu’au {fr(approval.end_at)}.")
    assertNotContains(response, "Aucun contrat en structure d’insertion connu.")
    assertNotContains(response, reverse("job_seekers_views:contracts", kwargs={"public_id": job_seeker.public_id}))
    # The name stays masked for a job seeker they did not create, and so do their contact details.
    assertNotContains(response, job_seeker.last_name)
    assertNotContains(response, job_seeker.email)
    assertContains(response, "Masquées pour vous")
    assertContains(response, "Aucun accompagnement en cours.")


def test_file_parts(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    company = membership.company
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(company=company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date)
    job_seeker = contract.job_seeker
    ApprovalFactory(user=job_seeker, start_at=contract.start_date)
    job_application = JobApplicationFactory(
        job_seeker=job_seeker, to_company=company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    # Sent to another company: not in this employer's scope.
    JobApplicationFactory(job_seeker=job_seeker, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True)
    report = ProSupportReportFactory(contract=contract, company=company)
    client.force_login(membership.user)

    response = client.get(page_url(job_seeker))
    parts = {part.key: part for part in response.context["file_parts"]}
    assert list(parts) == [
        "approval",
        "eligibility",
        "contracts",
        "job_applications",
        "report",
        "personal_information",
    ]
    assert (parts["approval"].badge_label, parts["approval"].badge_classes) == (
        "Valide",
        "bg-success-lighter text-success",
    )
    # A contract over, in grey, where it took place.
    [contract_fact] = parts["contracts"].facts
    assert (contract_fact.label, contract_fact.badge_label) == ("Chez vous", "Terminé")
    assert contract_fact.badge_classes == "bg-light text-muted"
    # Only this employer's job applications, with the platform's state badge.
    assert parts["job_applications"].summary == "1 candidature"
    assert [fact.job_application for fact in parts["job_applications"].facts] == [job_application]
    # Each opens in the side drawer.
    panel_url = reverse(
        "next_steps_views:job_application",
        kwargs={"public_id": job_seeker.public_id, "job_application_id": job_application.pk},
    )
    assert [fact.url for fact in parts["job_applications"].facts] == [panel_url]
    assertContains(response, f'hx-get="{panel_url}"')
    report_url = reverse(
        "next_steps_views:pro_support_report",
        kwargs={"public_id": job_seeker.public_id, "report_id": report.public_id},
    )
    assert parts["report"].link_url == report_url
    # The employer may see the contact details.
    assert parts["personal_information"].summary == job_seeker.email
    assertContains(response, "Lire le bilan")


def test_queue_links_names_to_this_page(client):
    membership = CompanyMembershipFactory()
    job_application = JobApplicationFactory(
        to_company=membership.company, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(membership.user)

    response = client.get(reverse("next_steps_views:todo"))
    assertContains(response, page_url(job_application.job_seeker))


def test_expired_diagnosis_covered_by_the_approval(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
    approval = ApprovalFactory(user=diagnosis.job_seeker, eligibility_diagnosis=diagnosis)
    client.force_login(membership.user)

    response = client.get(page_url(approval.user))
    assertContains(response, f"Couvert par le PASS IAE jusqu’au {fr(approval.end_at)}")
    assertNotContains(response, f"Valide jusqu’au {fr(diagnosis.expires_at)}")


def test_professional_assigned_with_and_without_organization_is_shown_once(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    job_seeker = JobSeekerFactory()
    JobSeekerAssignmentFactory(
        job_seeker=job_seeker, professional=membership.user, prescriber_organization=membership.organization
    )
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=membership.user, prescriber_organization=None)
    client.force_login(membership.user)

    response = client.get(page_url(job_seeker))
    assertContains(response, "· vous", count=1)
    assertContains(response, membership.organization.display_name)
    assertNotContains(response, "Aucune structure associée")


def test_strip_for_employer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract = ContractFactory(
        company=membership.company,
        start_date=timezone.localdate() - datetime.timedelta(days=200),
        end_date=timezone.localdate() - datetime.timedelta(days=10),
    )
    ApprovalFactory(user=contract.job_seeker, start_at=contract.start_date)
    client.force_login(membership.user)

    response = client.get(page_url(contract.job_seeker))
    assertContains(response, "next-step-frise__block--pass")
    assertContains(response, "Contrat chez vous")


def test_nothing_to_draw_without_pass_nor_contract(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    client.force_login(membership.user)

    response = client.get(page_url(JobSeekerFactory()))
    assertNotContains(response, "next-step-frise")


# Side drawers of the file
# ------------------------------------------------------------------------------


def test_job_application_drawer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    job_application = JobApplicationFactory(
        to_company=membership.company,
        state=JobApplicationState.NEW,
        sent_by_authorized_prescriber=True,
        message="Motivé et disponible.",
    )
    job_seeker = job_application.job_seeker
    # Sent to another company: not in this employer's scope.
    elsewhere = JobApplicationFactory(
        job_seeker=job_seeker, state=JobApplicationState.NEW, sent_by_authorized_prescriber=True
    )
    client.force_login(membership.user)

    def url(job_application):
        return reverse(
            "next_steps_views:job_application",
            kwargs={"public_id": job_seeker.public_id, "job_application_id": job_application.pk},
        )

    response = client.get(url(job_application), HTTP_HX_REQUEST="true")
    # What the "Candidature" section of its own page shows: the sender, the message, the jobs.
    assertContains(response, job_application.sender.get_full_name().split()[-1].upper())
    assertContains(response, job_application.sender_prescriber_organization.display_name)
    assertContains(response, "Motivé et disponible.")
    assertContains(response, "Candidature spontanée")
    full_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    assertContains(response, f"{full_url}?back_url=")
    assertContains(response, '<button type="button" class="btn-close" data-bs-dismiss="offcanvas"')
    # Without JavaScript, a page, with nothing to close.
    response = client.get(url(job_application))
    assertContains(response, "Motivé et disponible.")
    assertNotContains(response, '<button type="button" class="btn-close" data-bs-dismiss="offcanvas"')
    assert client.get(url(elsewhere), HTTP_HX_REQUEST="true").status_code == 404


def test_suspension_drawer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    approval = ApprovalFactory(start_at=timezone.localdate() - datetime.timedelta(days=100))
    suspension = SuspensionFactory(
        approval=approval,
        start_at=timezone.localdate() - datetime.timedelta(days=5),
        end_at=timezone.localdate() + datetime.timedelta(days=30),
        reason=Suspension.Reason.FINISHED_CONTRACT,
        siae=membership.company,
    )
    job_seeker = approval.user
    client.force_login(membership.user)

    url = reverse(
        "next_steps_views:suspension", kwargs={"public_id": job_seeker.public_id, "suspension_id": suspension.pk}
    )
    # The ongoing suspension of the file opens in the side drawer.
    assertContains(client.get(page_url(job_seeker)), f'hx-get="{url}"')
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, f"Du {fr(suspension.start_at)} au {fr(suspension.end_at)}")
    assertContains(response, Suspension.Reason.FINISHED_CONTRACT.label)
    assertContains(response, membership.company.display_name)
    # Another job seeker's suspension is not found from this page.
    other = JobSeekerFactory()
    other_url = reverse(
        "next_steps_views:suspension", kwargs={"public_id": other.public_id, "suspension_id": suspension.pk}
    )
    assert client.get(other_url, HTTP_HX_REQUEST="true").status_code == 404


def test_eligibility_drawer(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
    job_seeker = diagnosis.job_seeker
    client.force_login(membership.user)

    url = reverse("next_steps_views:eligibility", kwargs={"public_id": job_seeker.public_id})
    assertContains(client.get(page_url(job_seeker)), f'hx-get="{url}"')
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, "Valide jusqu’au")
    assertContains(response, fr(diagnosis.expires_at))
    assertContains(response, "Bénéficiaire du RSA")

    # Without a diagnosis to show, nothing to open.
    other_url = reverse("next_steps_views:eligibility", kwargs={"public_id": JobSeekerFactory().public_id})
    assert client.get(other_url, HTTP_HX_REQUEST="true").status_code == 404


def test_pro_support_report_drawer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    end_date = timezone.localdate() - datetime.timedelta(days=10)
    contract = ContractFactory(
        company=membership.company, start_date=end_date - datetime.timedelta(days=200), end_date=end_date
    )
    report = ProSupportReportFactory(
        contract=contract, company=membership.company, barriers=[ProSupportReportBarrier.MOBILITY]
    )
    job_seeker = contract.job_seeker
    client.force_login(membership.user)

    url = reverse(
        "next_steps_views:pro_support_report",
        kwargs={"public_id": job_seeker.public_id, "report_id": report.public_id},
    )
    # The file's "Lire le bilan" opens it in the side drawer.
    assertContains(client.get(page_url(job_seeker)), f'hx-get="{url}"')
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, f"Contrat terminé le {fr(end_date)}")
    # Each barrier with its icon, the autonomy on a gauge of five steps.
    assertContains(response, ProSupportReportBarrier.MOBILITY.label)
    assertContains(response, "ri-car-line")
    assertContains(response, f"{report.autonomy} sur 5")
    assertContains(response, 'class="flex-grow-1 rounded-pill bg-tertiary"', count=report.autonomy)
    # Without JavaScript, a page.
    assertContains(client.get(url), ProSupportReportBarrier.MOBILITY.label)

    # Another company's employer may not read it.
    client.force_login(CompanyMembershipFactory(company__subject_to_iae_rules=True).user)
    assert client.get(url, HTTP_HX_REQUEST="true").status_code == 404


def test_approval_drawer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    approval = ApprovalFactory(start_at=timezone.localdate() - datetime.timedelta(days=100))
    job_seeker = approval.user
    JobApplicationFactory(
        job_seeker=job_seeker,
        to_company=membership.company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        approval=approval,
    )
    suspension = SuspensionFactory(
        approval=approval,
        start_at=timezone.localdate() - datetime.timedelta(days=50),
        end_at=timezone.localdate() - datetime.timedelta(days=20),
        reason=Suspension.Reason.SICKNESS,
        siae=membership.company,
    )
    approval.refresh_from_db()
    client.force_login(membership.user)

    url = reverse("next_steps_views:approval", kwargs={"public_id": job_seeker.public_id})
    # The file's « Voir le PASS IAE » opens it in the side drawer.
    assertContains(client.get(page_url(job_seeker)), f'hx-get="{url}"')
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, approval.number_with_spaces)
    assertContains(response, "next-step-frise__block--pass")
    assertContains(response, f"Du {fr(suspension.start_at)} au {fr(suspension.end_at)}")
    assertContains(response, Suspension.Reason.SICKNESS.label)
    assertContains(response, "Aucune prolongation")
    # Its own page keeps the actions.
    assertContains(response, reverse("approvals:details", kwargs={"public_id": approval.public_id}))

    # An employer who never received an application from them may not see it.
    client.force_login(CompanyMembershipFactory(company__subject_to_iae_rules=True).user)
    assert client.get(url, HTTP_HX_REQUEST="true").status_code == 404


def test_contract_line_opens_in_the_drawer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    contract = ContractFactory(
        company=membership.company,
        start_date=timezone.localdate() - datetime.timedelta(days=200),
        end_date=timezone.localdate() - datetime.timedelta(days=10),
        details=[
            {
                "Type Contrat": "initial",
                "Contrat Date Embauche": fr_iso(timezone.localdate() - datetime.timedelta(days=200)),
                "Contrat Date Fin Contrat": fr_iso(timezone.localdate() - datetime.timedelta(days=10)),
                "Contrat Date Sortie Definitive": None,
            }
        ],
    )
    job_seeker = contract.job_seeker
    ApprovalFactory(user=job_seeker, start_at=contract.start_date)
    client.force_login(membership.user)

    url = reverse("next_steps_views:contract", kwargs={"public_id": job_seeker.public_id, "contract_id": contract.pk})
    # Under the strip: the contract, ended, and how the PASS IAE covers it; a click opens it in the side drawer.
    response = client.get(page_url(job_seeker))
    [line] = response.context["contract_lines"]
    assert (line.label, line.ongoing, line.coverage.variant) == ("Contrat chez vous", False, "warn")
    assertContains(response, f'hx-get="{url}"')

    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, membership.company.display_name)
    assertContains(response, f"Du {fr(contract.start_date)} au {fr(contract.end_date)}")
    assertContains(response, f"PASS{NBSP}IAE consommés depuis, sans contrat")
    # Its records in the ASP data.
    assertContains(response, "Déclaré à l’ASP")
    assertContains(response, "Initial")
    assertContains(response, f"Fin prévue le {fr(contract.end_date)}")
    # Without JavaScript, a page.
    assertContains(client.get(url), "Déclaré à l’ASP")

    # Another job seeker's contract is not found from this page.
    other = reverse(
        "next_steps_views:contract", kwargs={"public_id": JobSeekerFactory().public_id, "contract_id": contract.pk}
    )
    assert client.get(other, HTTP_HX_REQUEST="true").status_code == 404
