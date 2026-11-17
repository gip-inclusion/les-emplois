import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains

from itou.companies.enums import ProSupportReportBarrier as Barrier
from itou.eligibility.enums import AdministrativeCriteriaKind as Kind
from itou.insertion.enums import GenericReferenceItemKind, OrientationStatus
from itou.job_applications.enums import SenderKind
from tests.companies.factories import CompanyMembershipFactory, ProSupportReportFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.insertion.factories import GenericReferenceItemFactory, OrientationFactory, ServiceFactory
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
    ProSupportReportFactory(
        contract__company=company,
        contract__job_seeker=job_seeker,
        barriers=[Barrier.MOBILITY, Barrier.DIGITAL],
        created_at=days_ago(400),
    )
    ProSupportReportFactory(
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
    # In the report before, no longer in the latest one.
    assert keys(barriers.lifted) == [Barrier.DIGITAL]
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
