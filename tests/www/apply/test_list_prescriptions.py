import datetime
import itertools
import uuid
from urllib.parse import unquote

import factory
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import Title
from itou.utils.urls import add_url_params
from itou.www.apply.views.list_views import JobApplicationOrder, JobApplicationsDisplayKind
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import (
    assert_previous_step,
    assertSnapshotQueries,
    get_rows_from_streaming_response,
    parse_response_to_soup,
    pretty_indented,
)


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
    # Has link to export with back_url set
    exports_link = unquote(
        reverse("apply:list_prescriptions_exports", query={"back_url": reverse("apply:list_prescriptions")})
    )
    assertContains(response, exports_link)

    # Has job application link with back_url set
    job_application_link = unquote(
        reverse(
            "apply:details_for_prescriber",
            kwargs={"job_application_id": job_application.pk},
            query={"back_url": reverse("apply:list_prescriptions")},
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

    assertContains(response, job_application.job_seeker.get_full_name())


def test_queries(client, snapshot):
    prescriber = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True).sender
    JobApplicationFactory(sender=prescriber)
    client.force_login(prescriber)

    with assertSnapshotQueries(snapshot(name="SQL queries in list mode")):
        response = client.get(reverse("apply:list_prescriptions"), {"display": JobApplicationsDisplayKind.LIST})
    assert len(response.context["job_applications_page"].object_list) == 2

    with assertSnapshotQueries(snapshot(name="SQL queries in table mode")):
        response = client.get(reverse("apply:list_prescriptions"), {"display": JobApplicationsDisplayKind.TABLE})
    assert len(response.context["job_applications_page"].object_list) == 2


def test_as_unauthorized_prescriber(client, snapshot):
    prescriber = PrescriberFactory()
    JobApplicationFactory(
        job_seeker__first_name="Supersecretname",
        job_seeker__last_name="Unknown",
        job_seeker__created_by=PrescriberFactory(),  # to check for useless queries
        job_seeker__with_mocked_address=True,
        sender=prescriber,
        sender_kind=SenderKind.PRESCRIBER,
    )
    JobApplicationFactory(
        job_seeker__first_name="Liz",
        job_seeker__last_name="Ible",
        job_seeker__created_by=prescriber,  # to check for useless queries
        job_seeker__with_mocked_address=True,
        sender=prescriber,
        sender_kind=SenderKind.PRESCRIBER,
    )
    client.force_login(prescriber)

    list_url = reverse("apply:list_prescriptions")
    with assertSnapshotQueries(snapshot(name="SQL queries for prescriptions list")):
        response = client.get(list_url)

    assertContains(response, "<h3>S… U…</h3>")
    assertNotContains(response, "Supersecretname")
    assertContains(response, "<h3>Liz IBLE</h3>")


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
    prescriber = PrescriberMembershipFactory(organization__authorized=True).user
    JobApplicationFactory(sender=prescriber, job_seeker=job_seeker)
    JobApplicationFactory.create_batch(2, sender=prescriber)
    client.force_login(prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"job_seeker": job_seeker.pk})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].job_seeker.pk == job_seeker.pk

    response = client.get(reverse("apply:list_prescriptions"))

    filters_form = response.context["filters_form"]
    assert len(filters_form.fields["job_seeker"].choices) == 3

    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 3


def test_filtered_by_job_seeker_for_unauthorized_prescriber(client):
    prescriber = PrescriberFactory()
    a_b_job_seeker = JobApplicationFactory(
        sender=prescriber, job_seeker__first_name="A_something", job_seeker__last_name="B_something"
    ).job_seeker
    created_job_seeker = JobApplicationFactory(
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__first_name="Zorro",
        job_seeker__last_name="Martin",
    ).job_seeker
    c_d_job_seeker = JobApplicationFactory(
        sender=prescriber,
        job_seeker__created_by=prescriber,
        job_seeker__last_login=timezone.now(),
        job_seeker__first_name="C_something",
        job_seeker__last_name="D_something",
    ).job_seeker
    client.force_login(prescriber)

    response = client.get(reverse("apply:list_prescriptions"), {"job_seeker": created_job_seeker.pk})
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 1
    assert applications[0].job_seeker.pk == created_job_seeker.pk

    response = client.get(reverse("apply:list_prescriptions"))
    applications = response.context["job_applications_page"].object_list
    assert len(applications) == 3
    filters_form = response.context["filters_form"]
    assert filters_form.fields["job_seeker"].choices == [
        (a_b_job_seeker.pk, "A… B…"),
        (c_d_job_seeker.pk, "C… D…"),
        (created_job_seeker.pk, "Zorro MARTIN"),
    ]


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


def test_filtered_by_eligibility_state_prescriber(client):
    eligibility_validated_jobapp = JobApplicationFactory()
    eligibility_pending_jobapp = JobApplicationFactory(
        sender=eligibility_validated_jobapp.sender, eligibility_diagnosis=None
    )
    client.force_login(eligibility_validated_jobapp.sender)
    response = client.get(reverse("apply:list_prescriptions"), {"eligibility_validated": "on"})
    applications = response.context["job_applications_page"].object_list
    assert applications == [eligibility_validated_jobapp]
    response = client.get(reverse("apply:list_prescriptions"), {"eligibility_pending": "on"})
    applications = response.context["job_applications_page"].object_list
    assert applications == [eligibility_pending_jobapp]


def test_list_display_kind(client):
    prescriber_jobapp = JobApplicationFactory()
    client.force_login(prescriber_jobapp.sender)
    url = reverse("apply:list_prescriptions")

    TABLE_VIEW_MARKER = '<caption class="visually-hidden">Liste des candidatures'
    LIST_VIEW_MARKER = '<div class="c-box--results__header">'

    for display_param, expected_marker in [
        ({}, LIST_VIEW_MARKER),
        ({"display": "invalid"}, LIST_VIEW_MARKER),
        ({"display": JobApplicationsDisplayKind.LIST}, LIST_VIEW_MARKER),
        ({"display": JobApplicationsDisplayKind.TABLE}, TABLE_VIEW_MARKER),
    ]:
        response = client.get(url, display_param)
        for marker in (LIST_VIEW_MARKER, TABLE_VIEW_MARKER):
            if marker == expected_marker:
                assertContains(response, marker)
            else:
                assertNotContains(response, marker)


def test_filters(client, snapshot):
    client.force_login(PrescriberFactory())

    response = client.get(reverse("apply:list_prescriptions"))
    assert response.status_code == 200
    filter_form = parse_response_to_soup(response, "#offcanvasApplyFilters")
    assert pretty_indented(filter_form) == snapshot()


def test_archived(client):
    prescriber = PrescriberFactory()
    active = JobApplicationFactory(sender=prescriber)
    archived = JobApplicationFactory(sender=prescriber, archived_at=timezone.now())
    archived_badge_html = """\
    <span class="badge rounded-pill badge-sm mb-1 bg-light text-primary"
          aria-label="candidature archivée"
          data-bs-toggle="tooltip"
          data-bs-placement="top"
          data-bs-title="Candidature archivée">
      <i class="ri-archive-line mx-0"></i>
    </span>
    """
    client.force_login(prescriber)
    url = reverse("apply:list_prescriptions")
    response = client.get(url)
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"archived": ""})
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"archived": "archived"})
    assertNotContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"archived": "all"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"archived": "invalid"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    assertContains(
        response,
        """
        <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
            <p>
                <strong>Votre formulaire contient une erreur</strong>
            </p>
            <ul class="mb-0">
                <li>Sélectionnez un choix valide. invalid n’en fait pas partie.</li>
            </ul>
        </div>
        """,
        html=True,
        count=1,
    )


def test_htmx_filters(client):
    prescriber = PrescriberFactory()
    JobApplicationFactory(sender=prescriber, state=JobApplicationState.ACCEPTED)
    client.force_login(prescriber)

    url = reverse("apply:list_prescriptions")
    response = client.get(url)
    page = parse_response_to_soup(response, selector="#main")
    # Simulate the data-emplois-sync-with and check both checkboxes.
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

    # Switch display kind
    [display_input] = page.find_all(id="display-kind")
    display_input["value"] = JobApplicationsDisplayKind.TABLE.value

    response = client.get(
        url,
        {"states": ["refused"], "display": JobApplicationsDisplayKind.TABLE},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)

    response = client.get(url, {"states": ["refused"], "display": JobApplicationsDisplayKind.TABLE})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


@freeze_time("2024-11-27", tick=True)
def test_list_snapshot(client, snapshot):
    prescriber_org = PrescriberOrganizationWithMembershipFactory(for_snapshot=True)
    prescriber = prescriber_org.members.get()
    client.force_login(prescriber)
    url = reverse("apply:list_prescriptions")

    for display_param in [
        {},
        {"display": JobApplicationsDisplayKind.LIST},
        {"display": JobApplicationsDisplayKind.TABLE},
    ]:
        response = client.get(url, display_param)
        page = parse_response_to_soup(response, selector="#job-applications-section")
        assert pretty_indented(page) == snapshot(name="empty")

    job_seeker = JobSeekerFactory(for_snapshot=True)
    company = CompanyFactory(for_snapshot=True, with_membership=True)
    common_kwargs = {
        "job_seeker": job_seeker,
        "eligibility_diagnosis": None,
        "to_company": company,
        "sender_kind": SenderKind.PRESCRIBER,
        "sender": prescriber,
    }

    job_applications = [
        JobApplicationFactory(state=JobApplicationState.ACCEPTED, **common_kwargs),
        JobApplicationFactory(
            state=JobApplicationState.NEW,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.REFUSED,
            **common_kwargs,
        ),
    ]

    # List display
    response = client.get(url, {"display": JobApplicationsDisplayKind.LIST})
    page = parse_response_to_soup(
        response,
        selector="#job-applications-section",
        replace_in_attr=itertools.chain(
            [("href", f"/company/{company.pk}/card", "/company/[PK of Company]/card")],
            *(
                [
                    (
                        "href",
                        f"/apply/{job_application.pk}/prescriber/details",
                        "/apply/[PK of JobApplication]/prescriber/details",
                    ),
                    (
                        "id",
                        f"state_{job_application.pk}",
                        "state_[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            ),
        ),
    )
    assert pretty_indented(page) == snapshot(name="applications list")

    # Table display
    response = client.get(url, {"display": JobApplicationsDisplayKind.TABLE})
    page = parse_response_to_soup(
        response,
        selector="#job-applications-section",
        replace_in_attr=itertools.chain(
            *(
                [
                    (
                        "href",
                        f"/apply/{job_application.pk}/prescriber/details",
                        "/apply/[PK of JobApplication]/prescriber/details",
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
    assert pretty_indented(page) == snapshot(name="applications table")


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
        sender_prescriber_organization__kind=PrescriberOrganizationKind.FT,
    )
    client.force_login(job_application.sender)

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assert_previous_step(response, reverse("dashboard:index"))
    assertContains(response, "Toutes les candidatures")
    soup = parse_response_to_soup(response, selector=f"#{BESOIN_DUN_CHIFFRE}")
    assert pretty_indented(soup) == snapshot


def test_exports_as_employer(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_prescriptions_exports"))
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


def test_exports_back_to_list(client):
    client.force_login(PrescriberFactory())

    response = client.get(
        reverse("apply:list_prescriptions_exports", query={"back_url": reverse("apply:list_prescriptions")})
    )
    assert_previous_step(response, reverse("apply:list_prescriptions"), back_to_list=True)
    assertNotContains(response, BESOIN_DUN_CHIFFRE)


@freeze_time("2024-08-18")
def test_exports_download(client, snapshot):
    job_application = JobApplicationFactory(for_snapshot=True)
    JobApplicationFactory(
        created_at=timezone.now() - datetime.timedelta(days=1),  # Force application order
        job_seeker__title=Title.M,
        job_seeker__first_name="Secret",
        job_seeker__last_name="Undisclosed",
        job_seeker__email="undisclosed@secr.et",
        job_seeker__phone="3949",
        job_seeker__jobseeker_profile__birthdate=datetime.date(2000, 1, 2),
        to_company__name="Le fameux garage",
        sender=job_application.sender,
    )
    client.force_login(job_application.sender)

    # Make sure the prescriber has access to the first job seeker
    job_application.job_seeker.created_by = job_application.sender
    job_application.job_seeker.save(update_fields=("created_by",))

    with assertSnapshotQueries(snapshot(name="SQL queries of export")):
        response = client.get(reverse("apply:list_prescriptions_exports_download"))
        assert 200 == response.status_code
        assert "spreadsheetml" in response.get("Content-Type")
        rows = get_rows_from_streaming_response(response)

    assert rows == snapshot(name="export content")


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


def test_reset_filter_button_snapshot(client, snapshot):
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)

    filter_params = {"states": [job_application.state]}
    response = client.get(reverse("apply:list_prescriptions"), filter_params)

    assert pretty_indented(parse_response_to_soup(response, selector="#apply-list-filter-counter")) == snapshot(
        name="reset-filter button in list view"
    )
    assert pretty_indented(parse_response_to_soup(response, selector="#offcanvasApplyFiltersButtons")) == snapshot(
        name="off-canvas buttons in list view"
    )

    filter_params["display"] = JobApplicationsDisplayKind.TABLE
    filter_params["order"] = JobApplicationOrder.CREATED_AT_ASC
    response = client.get(reverse("apply:list_prescriptions"), filter_params)

    assert pretty_indented(parse_response_to_soup(response, selector="#apply-list-filter-counter")) == snapshot(
        name="reset-filter button in table view & created_at ascending order"
    )
    assert pretty_indented(parse_response_to_soup(response, selector="#offcanvasApplyFiltersButtons")) == snapshot(
        name="off-canvas buttons in table view & created_at ascending order"
    )


def test_order(client, subtests):
    zorro_application = JobApplicationFactory(
        job_seeker__first_name="Zorro",
        job_seeker__last_name="Don Diego",
    )
    prescriber = zorro_application.sender
    alice_first_application = JobApplicationFactory(
        job_seeker__first_name="Alice",
        job_seeker__last_name="Lewis",
        sender=prescriber,
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    alice_second_application = JobApplicationFactory(
        job_seeker__first_name="Alice",
        job_seeker__last_name="Lewis",
        sender=prescriber,
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )

    client.force_login(prescriber)
    url = reverse("apply:list_prescriptions")
    query_params = {"display": JobApplicationsDisplayKind.TABLE}

    expected_order = {
        "created_at": [zorro_application, alice_first_application, alice_second_application],
        "job_seeker_full_name": [alice_first_application, alice_second_application, zorro_application],
    }

    with subtests.test(order="<missing_value>"):
        response = client.get(url, query_params)
        assert response.context["job_applications_page"].object_list == list(reversed(expected_order["created_at"]))

    with subtests.test(order="<invalid_value>"):
        response = client.get(url, query_params | {"order": "invalid_value"})
        assert response.context["job_applications_page"].object_list == list(reversed(expected_order["created_at"]))

    for order, applications in expected_order.items():
        with subtests.test(order=order):
            response = client.get(url, query_params | {"order": order})
            assert response.context["job_applications_page"].object_list == applications

            response = client.get(url, query_params | {"order": f"-{order}"})
            assert response.context["job_applications_page"].object_list == list(reversed(applications))


def test_htmx_order(client):
    url = reverse("apply:list_prescriptions")

    job_app = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
    prescriber = job_app.sender
    JobApplicationFactory(sender=prescriber)
    client.force_login(prescriber)
    query_params = {"display": JobApplicationsDisplayKind.TABLE}
    response = client.get(url, query_params)

    assertContains(response, "2 résultats")
    simulated_page = parse_response_to_soup(response)

    ORDER_ID = "id_order"
    CREATED_AT_ASC = "created_at"
    assert response.context["order"] != CREATED_AT_ASC

    [sort_by_created_at_button] = simulated_page.find_all("button", {"data-emplois-setter-value": CREATED_AT_ASC})
    assert sort_by_created_at_button["data-emplois-setter-target"] == f"#{ORDER_ID}"
    [order_input] = simulated_page.find_all(id=ORDER_ID)
    # Simulate click on button
    order_input["value"] = CREATED_AT_ASC
    response = client.get(url, query_params | {"order": CREATED_AT_ASC}, headers={"HX-Request": "true"})
    update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
    response = client.get(url, query_params | {"order": CREATED_AT_ASC})
    assertContains(response, "2 résultats")
    fresh_page = parse_response_to_soup(response)
    assertSoupEqual(simulated_page, fresh_page)
