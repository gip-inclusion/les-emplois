import pytest
from django.urls import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains

from tests.prescribers.factories import (
    PrescriberMembershipFactory,
)
from tests.users.factories import JobSeekerFactory


def details_markup(expected_url):
    return f"""<a href="{escape(expected_url)}"
                  class="btn btn-lg bin-ico btn-secondary"
                  data-matomo-event="true"
                  data-matomo-category="candidat"
                  data-matomo-action="clic"
                  data-matomo-option="services-search-from-details-general"
                  id="introjs-orienter-vers-service-insertion">
                   <i class="ri-user-location-line fw-medium" aria-hidden="true"></i>
                   Orienter vers un service d’insertion
               </a>"""


def details_url(job_seeker):
    return reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})


def job_applications_markup(expected_url):
    return f"""<a href="{escape(expected_url)}"
                  class="btn btn-lg bin-ico btn-secondary"
                  data-matomo-event="true"
                  data-matomo-category="candidat"
                  data-matomo-action="clic"
                  data-matomo-option="services-search-from-details-job-applications">
                   <i class="ri-user-location-line fw-medium" aria-hidden="true"></i>
                   Orienter vers un service d’insertion
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
