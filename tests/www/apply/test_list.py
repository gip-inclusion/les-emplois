import uuid

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.www.apply.views.list_views import JobApplicationOrder, JobApplicationsDisplayKind
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


@freeze_time("2023-04-13")
def test_list_warns_about_long_awaiting_applications(client, snapshot):
    hit_pit = CompanyFactory(
        pk=42, name="Hit Pit", with_membership=True, not_in_territorial_experimentation=True, kind=CompanyKind.EI
    )

    now = timezone.now()
    org = PrescriberOrganizationFactory(
        membership__user__first_name="Max", membership__user__last_name="Throughput", with_membership=True
    )
    sender = org.active_members.get()
    job_seeker = JobSeekerFactory(
        first_name="Jacques", last_name="Henry", public_id=uuid.UUID("00000000-1111-2222-3333-444444444444")
    )
    JobApplicationFactory(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Third application",
        created_at=now - relativedelta(weeks=2),
    )
    JobApplicationFactory(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Second application",
        created_at=now - relativedelta(weeks=3, days=5),
    )
    JobApplicationFactory(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="First application",
        created_at=now - relativedelta(weeks=8),
    )

    client.force_login(hit_pit.members.get())
    response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.LIST})
    results_section = parse_response_to_soup(response, selector="#job-applications-section")

    assert pretty_indented(results_section) == snapshot(name="SIAE - warnings for 2222 and 3333")

    client.force_login(sender)
    response = client.get(reverse("apply:list_prescriptions"), {"display": JobApplicationsDisplayKind.LIST})
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert pretty_indented(results_section) == snapshot(name="PRESCRIBER - warnings for 2222 and 3333")

    client.force_login(job_seeker)
    response = client.get(reverse("apply:list_for_job_seeker"), {"display": JobApplicationsDisplayKind.LIST})
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert pretty_indented(results_section) == snapshot(name="JOB SEEKER - no warnings")


@pytest.mark.parametrize("order", JobApplicationOrder)
@pytest.mark.no_django_db
def test_opposite(order):
    assert order.opposite != order
    assert order.opposite.opposite == order
