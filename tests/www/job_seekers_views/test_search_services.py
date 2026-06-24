import pytest
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains

from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
)
from tests.users.factories import JobSeekerAssignmentFactory, JobSeekerFactory


def details_markup(expected_url):
    return f"""<a href="{escape(expected_url)}"
                  class="btn btn-lg btn-ico btn-secondary"
                  data-matomo-event="true"
                  data-matomo-category="candidat"
                  data-matomo-action="clic"
                  data-matomo-option="services-search-from-details-general"
                  id="introjs-orienter-vers-service-insertion">
                   <i class="ri-user-location-line fw-medium" aria-hidden="true"></i>
                   <span>Orienter vers un service d’insertion</span>
               </a>"""


def details_url(job_seeker):
    return reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})


def job_applications_markup(expected_url):
    return f"""<a href="{escape(expected_url)}"
                  class="btn btn-lg btn-ico btn-secondary"
                  data-matomo-event="true"
                  data-matomo-category="candidat"
                  data-matomo-action="clic"
                  data-matomo-option="services-search-from-details-job-applications"
                  id="introjs-orienter-vers-service-insertion">
                   <i class="ri-user-location-line fw-medium" aria-hidden="true"></i>
                   <span>Orienter vers un service d’insertion</span>
               </a>"""


def job_applications_url(job_seeker):
    return reverse("job_seekers_views:job_applications", kwargs={"public_id": job_seeker.public_id})


def list_markup(expected_url):
    return f"""<a href="{expected_url}"
                  class="dropdown-item"
                  data-matomo-event="true"
                  data-matomo-category="candidat"
                  data-matomo-action="clic"
                  data-matomo-option="services-search-from-list"
                  id="introjs-orienter-vers-service-insertion">
                Orienter vers un service d’insertion
            </a>"""


def list_url(_job_seeker):
    return reverse("job_seekers_views:list")


@pytest.mark.parametrize(
    "make_url,expected_markup",
    (
        pytest.param(details_url, details_markup, id="details_view"),
        pytest.param(job_applications_url, job_applications_markup, id="job_applications_view"),
        pytest.param(list_url, list_markup, id="list_view"),
    ),
)
@pytest.mark.parametrize("has_city_slug", (True, False))
def test_search_services_no_city(client, make_url, expected_markup, has_city_slug):
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    client.force_login(prescriber)
    job_seeker = JobSeekerFactory(created_by=prescriber, with_address=has_city_slug)
    JobSeekerAssignmentFactory(
        job_seeker=job_seeker,
        professional=prescriber,
    )

    url = make_url(job_seeker)
    response = client.get(url)

    query = {
        "job_seeker_public_id": job_seeker.public_id,
        "back_url": url,
    }
    if has_city_slug:
        query["city"] = job_seeker.city_slug
    expected_url = reverse("search:services_results", query=query)
    assertContains(
        response,
        expected_markup(expected_url),
        html=True,
    )


def assert_has_more_actions(response, list_url, job_seeker):
    query = {
        "job_seeker_public_id": job_seeker.public_id,
        "back_url": list_url,
    }
    if job_seeker.city_slug:
        query["city"] = job_seeker.city_slug
    expected_url = reverse("search:services_results", query=query)
    assertContains(response, list_markup(expected_url), html=True)
    assertContains(response, 'aria-label="Plus d\'actions"')


def test_search_services_from_list_as_authorized_prescriber(client):
    professional = PrescriberMembershipFactory(organization__authorized=True).user
    job_seeker = JobSeekerFactory(created_by=professional, with_address=True)
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=professional)
    ApprovalFactory(user=job_seeker)
    client.force_login(professional)
    list_url = reverse("job_seekers_views:list")

    assert_has_more_actions(client.get(list_url), list_url, job_seeker)


def test_search_services_from_list_as_orienteur(client):
    professional = PrescriberMembershipFactory(organization__authorized=False).user
    job_seeker = JobSeekerFactory(created_by=professional, with_address=True)
    JobSeekerAssignmentFactory(job_seeker=job_seeker, professional=professional)
    ApprovalFactory(user=job_seeker)
    client.force_login(professional)
    list_url = reverse("job_seekers_views:list")

    assert_has_more_actions(client.get(list_url), list_url, job_seeker)


def test_search_services_from_list_as_employer(client):
    membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
    professional = membership.user
    job_seeker = JobApplicationFactory(
        sent_by_employer=True,
        sender=professional,
        sender_company=membership.company,
        with_job_seeker_assignment=True,
    ).job_seeker
    ApprovalFactory(user=job_seeker)
    client.force_login(professional)
    list_url = reverse("job_seekers_views:list_organization")

    assert_has_more_actions(client.get(list_url), list_url, job_seeker)
