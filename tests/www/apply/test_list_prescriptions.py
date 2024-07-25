from urllib.parse import unquote

import factory
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.urls import add_url_params
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWith2MembershipFactory,
)
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import BASE_NUM_QUERIES, assert_previous_step, parse_response_to_soup


BESOIN_DUN_CHIFFRE = "besoin-dun-chiffre"


def test_get(client):
    """
    Connect as Thibault to see a list of job applications
    sent by his organization (Pôle emploi).
    """
    job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
    organization = job_application.sender_prescriber_organization
    client.force_login(job_application.sender)

    response = client.get(reverse("apply:list_prescriptions"))
    assert_previous_step(response, reverse("dashboard:index"))
    # Has link to export with back_url set
    exports_link = unquote(
        add_url_params(reverse("apply:list_prescriptions_exports"), {"back_url": reverse("apply:list_prescriptions")})
    )
    assertContains(response, exports_link)

    # Has job application link with back_url set
    job_application_link = unquote(
        add_url_params(
            reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk}),
            {"back_url": reverse("apply:list_prescriptions")},
        )
    )
    assertContains(response, job_application_link)

    # Has link to company with back_url set
    company_link = unquote(
        add_url_params(job_application.to_company.get_card_url(), {"back_url": reverse("apply:list_prescriptions")})
    )
    assertContains(response, company_link)

    # Count job applications used by the template
    assert len(response.context["job_applications_page"].object_list) == organization.jobapplication_set.count()


def test_as_unauthorized_prescriber(client):
    prescriber = PrescriberFactory()
    JobApplicationFactory(
        job_seeker_with_address=True,
        job_seeker__first_name="Supersecretname",
        job_seeker__last_name="Unknown",
        job_seeker__created_by=PrescriberFactory(),  # to check for useless queries
        sender=prescriber,
        sender_kind=SenderKind.PRESCRIBER,
    )
    client.force_login(prescriber)

    with assertNumQueries(
        BASE_NUM_QUERIES
        + 1  # fetch django session
        + 1  # fetch user
        + 1  # fetch user memberships
        + 1  # get list of senders (distinct sender_id)
        + 1  # get list of job seekers (distinct job_seeker_id)
        + 1  # get list of administrative criteria
        + 2  # get list of job application + prefetch of job descriptions
        + 1  # get list of siaes (distinct to_company_id)
        + 3  # count, list & prefetch of job application
        + 1  # get job seekers approvals
        + 1  # check user authorized membership (can_edit_personal_information)
        + 3  # get job seekers administrative criteria
        + 3  # update session
    ):
        response = client.get(reverse("apply:list_prescriptions"))

    assertContains(response, "<h3>S… U…</h3>", html=True)
    # Unfortunately, the job seeker's name is available in the filters
    # assertNotContains(response, "Supersecretname")


def test_filtered_by_state(client):
    """
    Thibault wants to filter a list of job applications
    by the default initial state.
    """
    prescriber = PrescriberFactory()
    job_application, *others = JobApplicationFactory.create_batch(
        3, sender=prescriber, state=factory.Iterator(JobApplicationWorkflow.states)
    )
    client.force_login(prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"states": [job_application.state]})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].state == job_application.state

    response = client.get(reverse("apply:list_prescriptions"))
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 3


def test_filtered_by_sender(client):
    organization = PrescriberOrganizationWith2MembershipFactory()
    a_prescriber, another_prescriber = organization.members.all()
    JobApplicationFactory(sender=another_prescriber, sender_prescriber_organization=organization)
    client.force_login(a_prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"senders": another_prescriber.pk})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].sender.id == another_prescriber.pk


def test_filtered_by_job_seeker(client):
    job_seeker = JobSeekerFactory()
    prescriber = PrescriberFactory()
    JobApplicationFactory(sender=prescriber, job_seeker=job_seeker)
    JobApplicationFactory.create_batch(2, sender=prescriber)
    client.force_login(prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"job_seeker": job_seeker.pk})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].job_seeker.pk == job_seeker.pk

    response = client.get(reverse("apply:list_prescriptions"))
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 3


def test_filtered_by_company(client):
    prescriber = PrescriberFactory()
    job_application, *others = JobApplicationFactory.create_batch(3, sender=prescriber)
    client.force_login(prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"to_companies": [job_application.to_company.pk]})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].to_company.pk == job_application.to_company.pk

    response = client.get(reverse("apply:list_prescriptions"))
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 3


def test_filtered_by_eligibility_validated_prescriber(client):
    prescriber_jobapp = JobApplicationFactory()
    client.force_login(prescriber_jobapp.sender)
    response = client.get(reverse("apply:list_prescriptions"), {"eligiblity_validated": "on"})
    applications = response.context["job_applications_page"].object_list
    assert applications == [prescriber_jobapp]


def test_filters(client, snapshot):
    client.force_login(PrescriberFactory())

    response = client.get(reverse("apply:list_prescriptions"))
    assert response.status_code == 200
    filter_form = parse_response_to_soup(response, "#offcanvasApplyFilters")
    assert str(filter_form) == snapshot()


def test_htmx_filters(client):
    prescriber = PrescriberFactory()
    JobApplicationFactory(sender=prescriber, state=JobApplicationState.ACCEPTED)
    client.force_login(prescriber)

    url = reverse("apply:list_prescriptions")
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


def test_exports_without_organization(client):
    client.force_login(PrescriberFactory())

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assert_previous_step(response, reverse("dashboard:index"))
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


def test_exports_with_organization(client):
    client.force_login(PrescriberFactory(membership=True))

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assert_previous_step(response, reverse("dashboard:index"))
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


def test_exports_as_pole_emploi_prescriber(client, snapshot):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        sender_prescriber_organization__kind=PrescriberOrganizationKind.PE,
    )
    client.force_login(job_application.sender)

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assert_previous_step(response, reverse("dashboard:index"))
    assertContains(response, "Toutes les candidatures")
    soup = parse_response_to_soup(response, selector=f"#{BESOIN_DUN_CHIFFRE}")
    assert str(soup) == snapshot


def test_exports_as_employer(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


def test_exports_back_to_list(client):
    client.force_login(PrescriberFactory())

    response = client.get(
        add_url_params(reverse("apply:list_prescriptions_exports"), {"back_url": reverse("apply:list_prescriptions")})
    )
    assert_previous_step(response, reverse("apply:list_prescriptions"), back_to_list=True)
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


def test_exports_download(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)

    response = client.get(reverse("apply:list_prescriptions_exports_download"))
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")


def test_exports_download_as_employer(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_prescriptions_exports_download"))
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")


def test_exports_download_by_month(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)

    response = client.get(
        reverse(
            "apply:list_prescriptions_exports_download",
            kwargs={"month_identifier": job_application.created_at.strftime("%Y-%d")},
        )
    )
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")
