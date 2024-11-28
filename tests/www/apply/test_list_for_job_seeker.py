import itertools

import factory
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.widgets import DuetDatePickerWidget
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
)
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import parse_response_to_soup


def test_list_for_job_seeker(client):
    job_seeker = JobApplicationSentByJobSeekerFactory().job_seeker
    JobApplicationSentByCompanyFactory(job_seeker=job_seeker)
    JobApplicationSentByPrescriberFactory(job_seeker=job_seeker)
    client.force_login(job_seeker)

    response = client.get(reverse("apply:list_for_job_seeker"))
    assert len(response.context["job_applications_page"].object_list) == 3


def test_filters(client, snapshot):
    client.force_login(JobSeekerFactory())

    response = client.get(reverse("apply:list_for_job_seeker"))
    assert response.status_code == 200
    filter_form = parse_response_to_soup(response, "#offcanvasApplyFilters")
    assert str(filter_form) == snapshot()


def test_list_for_job_seeker_filtered_by_state(client):
    """
    Provide a list of job applications sent by a job seeker
    and filtered by a state.
    """
    job_application, *others = JobApplicationSentByJobSeekerFactory.create_batch(
        3, state=factory.Iterator(JobApplicationWorkflow.states)
    )
    client.force_login(job_application.job_seeker)

    response = client.get(reverse("apply:list_for_job_seeker"), {"states": [job_application.state]})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].state == job_application.state


def test_list_for_job_seeker_filtered_by_dates(client):
    """
    Provide a list of job applications sent by a job seeker
    and filtered by dates
    """
    now = timezone.now()
    job_seeker = JobSeekerFactory()
    for diff_day in [7, 5, 3, 0]:
        JobApplicationSentByJobSeekerFactory(created_at=now - timezone.timedelta(days=diff_day), job_seeker=job_seeker)
    client.force_login(job_seeker)

    start_date = now - timezone.timedelta(days=5)
    end_date = now - timezone.timedelta(days=1)
    response = client.get(
        reverse("apply:list_for_job_seeker"),
        {
            "start_date": timezone.localdate(start_date).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "end_date": timezone.localdate(end_date).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        },
    )
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 2
    assert applications[0].created_at >= start_date
    assert applications[0].created_at <= end_date


def test_list_for_job_seeker_htmx_filters(client):
    job_seeker = JobSeekerFactory()
    JobApplicationFactory(job_seeker=job_seeker, state=JobApplicationState.ACCEPTED)
    client.force_login(job_seeker)

    url = reverse("apply:list_for_job_seeker")
    response = client.get(url)
    page = parse_response_to_soup(response, selector="#main")
    # Simulate the data-sync-with and check both checkboxes.
    refused_checkboxes = page.find_all(
        "input",
        attrs={"name": "states", "value": "refused"},
    )
    assert len(refused_checkboxes) == 2
    for refused_checkbox in refused_checkboxes:
        refused_checkbox["checked"] = ""

    response = client.get(
        url,
        {"states": ["refused"]},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)

    response = client.get(url, {"states": ["refused"]})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


@freeze_time("2024-11-27", tick=True)
def test_list_snapshot(client, snapshot):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    url = reverse("apply:list_for_job_seeker")

    response = client.get(url)
    page = parse_response_to_soup(response, selector="#job-applications-section")
    assert str(page) == snapshot(name="empty list")

    company = CompanyFactory(for_snapshot=True, with_membership=True)
    common_kwargs = {"job_seeker": job_seeker, "eligibility_diagnosis": None, "to_company": company}
    prescriber_org = PrescriberOrganizationWithMembershipFactory(for_snapshot=True)

    job_applications = [
        JobApplicationFactory(
            sender_kind=SenderKind.JOB_SEEKER, sender=job_seeker, state=JobApplicationState.ACCEPTED, **common_kwargs
        ),
        JobApplicationFactory(
            sender_kind=SenderKind.EMPLOYER,
            sender=company.members.first(),
            sender_company=company,
            state=JobApplicationState.NEW,
            **common_kwargs,
        ),
        JobApplicationFactory(
            sender_kind=SenderKind.PRESCRIBER,
            sender=prescriber_org.members.first(),
            sender_prescriber_organization=prescriber_org,
            state=JobApplicationState.REFUSED,
            **common_kwargs,
        ),
    ]

    response = client.get(url)
    page = parse_response_to_soup(
        response,
        selector="#job-applications-section",
        replace_in_attr=itertools.chain(
            *(
                [
                    (
                        "href",
                        f"/apply/{job_application.pk}/jobseeker/details",
                        "/apply/[PK of JobApplication]/jobseeker/details",
                    ),
                    (
                        "id",
                        f"state_{job_application.pk}",
                        "state_[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            )
        ),
    )
    assert str(page) == snapshot(name="applications list")
