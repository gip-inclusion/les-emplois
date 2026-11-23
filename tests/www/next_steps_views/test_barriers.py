import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertRedirects

from itou.companies.enums import ProSupportReportBarrier as Barrier
from itou.eligibility.enums import AdministrativeCriteriaKind as Kind
from itou.insertion.enums import GenericReferenceItemKind, OrientationStatus
from itou.job_applications.enums import SenderKind
from itou.next_steps.models import BarrierStatus, JobSeekerBarrier, LiftCause
from tests.companies.factories import CompanyMembershipFactory, ProSupportReportFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.insertion.factories import GenericReferenceItemFactory, OrientationFactory, ServiceFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import JobSeekerFactory


@pytest.fixture(autouse=True)
def experiment_for_everyone(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True


def days_ago(days):
    return timezone.now() - datetime.timedelta(days=days)


def page(client, job_seeker):
    return client.get(reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id}))


def keys(cards):
    return [card.key for card in cards]


def thematic(value):
    return GenericReferenceItemFactory(kind=GenericReferenceItemKind.THEMATIC, value=value, label=value)


@pytest.fixture
def employer():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True).user


def test_three_sources_in_three_columns(client, employer):
    company = employer.company_set.first()
    job_seeker = JobSeekerFactory()
    older = ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY, Barrier.DIGITAL],
        created_at=days_ago(400),
    )
    latest = ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY, Barrier.HEALTH],
        created_at=days_ago(10),
    )
    IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.RSA, Kind.FLE])
    orientation = OrientationFactory(
        beneficiary=job_seeker,
        sender=employer,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=company,
        sender_prescriber_organization=None,
        service=ServiceFactory(thematics=[thematic("mobilite--preparer-un-permis")]),
        status=OrientationStatus.PENDING,
    )
    # Refused: nothing in progress.
    OrientationFactory(
        beneficiary=job_seeker,
        sender=employer,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=company,
        sender_prescriber_organization=None,
        service=ServiceFactory(thematics=[thematic("sante--acces-aux-soins")]),
        status=OrientationStatus.REFUSED,
    )
    client.force_login(employer)

    response = page(client, job_seeker)
    barriers = response.context["barriers"]
    # Named in the latest report, or hinted at by the criteria (to confirm).
    assert keys(barriers.to_work) == [Barrier.HEALTH, Barrier.FINANCIAL, Barrier.LITERACY]
    assert [card.to_confirm for card in barriers.to_work] == [False, True, True]
    # An ongoing orientation towards a mobility service.
    assert keys(barriers.in_progress) == [Barrier.MOBILITY]
    # In the report before, no longer in the latest one: both open in the side drawer.
    assert keys(barriers.lifted) == [Barrier.DIGITAL]

    def report_url(report):
        return reverse(
            "next_steps_views:pro_support_report",
            kwargs={"public_id": job_seeker.public_id, "report_id": report.public_id},
        )

    assert [url for _, url in barriers.lifted[0].clues[0].reports] == [report_url(older), report_url(latest)]
    assertContains(response, f'hx-get="{report_url(older)}"')
    # A barrier named in the latest report leads to it too.
    assert barriers.to_work[0].clues[0].reports == [("Voir le bilan", report_url(latest))]
    assertContains(response, f"orientation vers « {orientation.service.name} »")
    assertContains(response, "Repéré par le diagnostic d’éligibilité IAE", count=2)


def test_the_latest_report_prevails_over_the_criteria(client, employer):
    company = employer.company_set.first()
    job_seeker = JobSeekerFactory()
    ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY],
        created_at=days_ago(400),
    )
    ProSupportReportFactory(
        contract__company=company, contract__job_seeker=job_seeker, barriers=[], created_at=days_ago(10)
    )
    IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.PM])
    client.force_login(employer)

    barriers = page(client, job_seeker).context["barriers"]
    assert keys(barriers.to_work) == []
    assert keys(barriers.lifted) == [Barrier.MOBILITY]


def test_criteria_alone(client, employer):
    job_seeker = JobSeekerFactory()
    IAEEligibilityDiagnosisFactory(
        from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.AAH, Kind.CAP_BEP]
    )
    client.force_login(employer)

    response = page(client, job_seeker)
    barriers = response.context["barriers"]
    # The allowance hints at health and money; a low education level is too weak a hint.
    assert keys(barriers.to_work) == [Barrier.HEALTH, Barrier.FINANCIAL]
    assertContains(response, "Aucun bilan d’accompagnement pour le moment.")


def test_find_a_solution_searches_services_around_the_job_seeker(client, employer):
    job_seeker = JobSeekerFactory(with_address=True)
    IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.PM])
    client.force_login(employer)

    response = page(client, job_seeker)
    [card] = response.context["barriers"].to_work
    page_url = reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id})
    assert card.search_url == reverse(
        "search:services_results",
        query={
            "back_url": page_url,
            "city": job_seeker.city_slug,
            "category": "mobilite",
            "job_seeker_public_id": job_seeker.public_id,
        },
    )
    assertContains(response, "Trouver une solution")


def test_an_ongoing_orientation_opens_in_the_drawer(client, employer):
    company = employer.company_set.first()
    job_seeker = JobSeekerFactory()
    orientation = OrientationFactory(
        beneficiary=job_seeker,
        sender=employer,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=company,
        sender_prescriber_organization=None,
        service=ServiceFactory(thematics=[thematic("numerique--acquerir-un-equipement")]),
        status=OrientationStatus.ACCEPTED,
    )
    # Sent by another organization: not theirs to read.
    elsewhere = OrientationFactory(beneficiary=job_seeker)
    client.force_login(employer)

    response = page(client, job_seeker)
    [card] = response.context["barriers"].in_progress
    panel_url = reverse(
        "next_steps_views:orientation", kwargs={"public_id": job_seeker.public_id, "orientation_id": orientation.pk}
    )
    assert card.clues[-1].url == panel_url
    assertContains(response, f'hx-get="{panel_url}"')

    response = client.get(panel_url, HTTP_HX_REQUEST="true")
    assertContains(response, orientation.service.name)
    assertContains(response, orientation.service.structure.name)
    assertContains(
        response, reverse("insertion_views:orientation_details_for_sender", kwargs={"orientation_id": orientation.pk})
    )
    # Without JavaScript, a page.
    assert client.get(panel_url).status_code == 200
    elsewhere_url = reverse(
        "next_steps_views:orientation", kwargs={"public_id": job_seeker.public_id, "orientation_id": elsewhere.pk}
    )
    assert client.get(elsewhere_url, HTTP_HX_REQUEST="true").status_code == 404


def statement_url(job_seeker, barrier, action):
    return reverse(
        "next_steps_views:barrier_statement",
        kwargs={"public_id": job_seeker.public_id, "barrier": barrier.lower(), "action": action},
    )


def test_lift_a_barrier_from_its_card(client, employer):
    company = employer.company_set.first()
    job_seeker = JobSeekerFactory()
    ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY, Barrier.DIGITAL],
        created_at=days_ago(10),
    )
    orientation = OrientationFactory(
        beneficiary=job_seeker,
        sender=employer,
        sender_kind=SenderKind.EMPLOYER,
        sender_company=company,
        sender_prescriber_organization=None,
        service=ServiceFactory(thematics=[thematic("mobilite--preparer-un-permis")]),
        status=OrientationStatus.ACCEPTED,
    )
    client.force_login(employer)

    barriers = page(client, job_seeker).context["barriers"]
    assert keys(barriers.in_progress) == [Barrier.MOBILITY]
    lift_url = statement_url(job_seeker, Barrier.MOBILITY, "leve")
    assert barriers.in_progress[0].lift_url == lift_url
    assert barriers.to_work[0].lift_url == statement_url(job_seeker, Barrier.DIGITAL, "leve")

    # A confirmation in the side drawer, offering the ongoing orientation on that barrier as the cause.
    response = client.get(lift_url, HTTP_HX_REQUEST="true")
    assertContains(response, "Marquer le frein comme levé")
    assertContains(response, f'value="orientation-{orientation.pk}"')
    assertContains(response, "La personne a trouvé une solution elle-même")
    # Without JavaScript, a page.
    assert client.get(lift_url).status_code == 200

    response = client.post(lift_url, {"cause": f"orientation-{orientation.pk}"})
    page_url = reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id})
    assertRedirects(response, page_url, fetch_redirect_response=False)

    response = page(client, job_seeker)
    barriers = response.context["barriers"]
    assert keys(barriers.in_progress) == []
    assert keys(barriers.to_work) == [Barrier.DIGITAL]
    [lifted] = barriers.lifted
    assert lifted.key == Barrier.MOBILITY
    assert lifted.back_url == statement_url(job_seeker, Barrier.MOBILITY, "revenu")
    assert lifted.lift_url == ""
    assert lifted.clues[0].text == (
        f"Levé le {timezone.localdate():%d/%m/%Y}, par {employer.get_full_name()} ({company.display_name})"
        f" · grâce à l’orientation vers « {orientation.service.name} »"
    )
    statement = JobSeekerBarrier.objects.get()
    assert statement.author_company == company
    assert statement.author_prescriber_organization is None
    assert statement.lift_cause == LiftCause.ORIENTATION

    # Among what was done today.
    response = client.get(reverse("next_steps_views:todo"))
    assertContains(response, f"frein levé : {Barrier.MOBILITY.label}")


def test_a_lifted_barrier_comes_back(client):
    membership = PrescriberMembershipFactory(organization__authorized=True)
    job_seeker = JobSeekerFactory()
    IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.PM])
    client.force_login(membership.user)

    response = client.post(statement_url(job_seeker, Barrier.MOBILITY, "leve"), {"cause": LiftCause.SELF})
    assert response.status_code == 302
    barriers = page(client, job_seeker).context["barriers"]
    assert keys(barriers.to_work) == []
    assert barriers.lifted[0].clues[0].text.endswith("· grâce à la personne a trouvé une solution elle-même")
    assert JobSeekerBarrier.objects.get().author_prescriber_organization == membership.organization

    back_url = statement_url(job_seeker, Barrier.MOBILITY, "revenu")
    response = client.get(back_url, HTTP_HX_REQUEST="true")
    assertContains(response, "Le frein est revenu")
    assertContains(response, "Le frein repassera dans «&nbsp;À travailler&nbsp;»")
    client.post(back_url)
    barriers = page(client, job_seeker).context["barriers"]
    assert keys(barriers.to_work) == [Barrier.MOBILITY]
    assert keys(barriers.lifted) == []
    assert barriers.to_work[0].clues[0].text.startswith(f"Revenu le {timezone.localdate():%d/%m/%Y}")


def test_a_later_report_prevails_over_a_lifted_barrier(client, employer):
    company = employer.company_set.first()
    job_seeker = JobSeekerFactory()
    JobSeekerBarrier.objects.create(
        job_seeker=job_seeker, barrier=Barrier.MOBILITY, status=BarrierStatus.LIFTED, created_at=days_ago(20)
    )
    ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY],
        created_at=days_ago(5),
    )
    client.force_login(employer)

    barriers = page(client, job_seeker).context["barriers"]
    assert keys(barriers.to_work) == [Barrier.MOBILITY]
    assert keys(barriers.lifted) == []


def test_who_can_state_a_barrier(client, employer):
    job_seeker = JobSeekerFactory()
    client.force_login(employer)
    # Only the report's barriers and the two actions.
    assert client.get(statement_url(job_seeker, "AUTRE", "leve")).status_code == 404
    assert client.get(statement_url(job_seeker, Barrier.MOBILITY, "supprime")).status_code == 404
    # Not for a prescriber without the authorization.
    client.force_login(PrescriberMembershipFactory(organization__authorized=False).user)
    assert client.post(statement_url(job_seeker, Barrier.MOBILITY, "leve")).status_code == 404
    assert not JobSeekerBarrier.objects.exists()
