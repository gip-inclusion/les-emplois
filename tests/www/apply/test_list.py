from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup


@freeze_time("2023-04-13")
def test_list_warns_about_long_awaiting_applications(client, snapshot):
    hit_pit = CompanyFactory(pk=42, name="Hit Pit", with_membership=True)

    now = timezone.now()
    org = PrescriberOrganizationWithMembershipFactory(
        membership__user__first_name="Max", membership__user__last_name="Throughput"
    )
    sender = org.active_members.get()
    job_seeker = JobSeekerFactory(first_name="Jacques", last_name="Henry")
    JobApplicationFactory(
        id="11111111-1111-1111-1111-111111111111",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Third application",
        created_at=now - relativedelta(weeks=2),
    )
    JobApplicationFactory(
        id="22222222-2222-2222-2222-222222222222",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="Second application",
        created_at=now - relativedelta(weeks=3, days=5),
    )
    JobApplicationFactory(
        id="33333333-3333-3333-3333-333333333333",
        to_company=hit_pit,
        job_seeker=job_seeker,
        sender=sender,
        message="First application",
        created_at=now - relativedelta(weeks=8),
    )

    client.force_login(hit_pit.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="SIAE - warnings for 2222 and 3333")

    client.force_login(sender)
    response = client.get(reverse("apply:list_prescriptions"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="PRESCRIBER - warnings for 2222 and 3333")

    client.force_login(job_seeker)
    response = client.get(reverse("apply:list_for_job_seeker"))
    results_section = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(results_section) == snapshot(name="JOB SEEKER - no warnings")
