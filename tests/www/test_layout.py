from functools import partial

import pytest
from django.urls import reverse

from itou.nexus.enums import Service
from itou.nexus.models import ActivatedService
from itou.users.enums import IdentityProvider
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.nexus.factories import NexusUserFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented, remove_static_hash


def set_org_id_for_snapshot(soup):
    for button in soup.find_all("button", {"name": "organization_key"}):
        button["value"] = "ORGANIZATION_KEY"


def test_navigation_not_authenticated(snapshot, client):
    response = client.get(reverse("home:hp"), follow=True)
    assert pretty_indented(parse_response_to_soup(response, "#nav-primary")) == snapshot


@pytest.mark.parametrize(
    "user_factory",
    [
        pytest.param(JobSeekerFactory, id="JobSeeker"),
        pytest.param(
            partial(
                EmployerFactory,
                membership=True,
                membership__company__for_snapshot=True,
                membership__company__not_in_territorial_experimentation=True,
            ),
            id="Employer",
        ),
        pytest.param(
            partial(
                LaborInspectorFactory,
                membership=True,
                membership__institution__name="ACME Inc.",
            ),
            id="LaborInspector",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__authorized=False,
                membership__organization__for_snapshot=True,
                membership__organization__not_in_territorial_experimentation=True,
            ),
            id="PrescriberWithUnauthorizedOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__authorized=True,
                membership__organization__for_snapshot=True,
                membership__organization__not_in_territorial_experimentation=True,
            ),
            id="PrescriberWithAuthorizedOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
            ),
            id="ProfessionalWithoutOrganization",
        ),
    ],
)
def test_navigation_authenticated(snapshot, client, user_factory):
    client.force_login(
        user_factory(
            for_snapshot=True,
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
        )
    )
    response = client.get(reverse("home:hp"), follow=True)
    soup = parse_response_to_soup(response)

    [nav_primary] = soup.select("#nav-primary")
    set_org_id_for_snapshot(nav_primary)
    assert pretty_indented(nav_primary) == snapshot(name="user menu")

    [offcanvasNav] = soup.select("#offcanvasNav")
    for a_tags in soup.find_all("a", attrs={"href": True}):
        if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
            a_tags["href"] = remove_static_hash(a_tags["href"])  # Normalize href for CI
    set_org_id_for_snapshot(offcanvasNav)
    assert pretty_indented(offcanvasNav) == snapshot(name="navigation")


def test_nav_dropdown_with_multiple_org_types(snapshot, client):
    # Force pks to be identical: only one menu entry should be `active`
    user = PrescriberMembershipFactory(
        organization__for_snapshot=True, user__for_snapshot=True, organization__pk=5001
    ).user
    CompanyMembershipFactory(company__for_snapshot=True, user=user, company__pk=5001)
    InstitutionMembershipFactory(institution__name="1 Titus Ion", user=user, institution__pk=5001)
    client.force_login(user)

    response = client.get(reverse("home:hp"), follow=True)
    soup = parse_response_to_soup(response)

    [switcher_nav] = soup.select("li.dropdown-organization")
    set_org_id_for_snapshot(switcher_nav)
    assert pretty_indented(switcher_nav) == snapshot(name="multi organization structure switcher in nav")

    [switcher_offcanvas] = soup.select("div.dropdown-organization")
    set_org_id_for_snapshot(switcher_offcanvas)
    assert pretty_indented(switcher_offcanvas) == snapshot(name="multi organization structure switcher in offcanvas")


@pytest.mark.parametrize("case", ["disabled", "enabled_no_proconnect", "enabled", "enabled_all_activated"])
def test_nexus_dropdown(snapshot, client, case, pro_connect):
    user = PrescriberFactory(
        for_snapshot=True,
        identity_provider=IdentityProvider.DJANGO if case == "enabled_no_proconnect" else IdentityProvider.PRO_CONNECT,
    )
    PrescriberMembershipFactory(
        user=user,
        organization__name="On vous aide",
        organization__siret="01234567891010",
        organization__post_code="31"
        if case in ["enabled_no_proconnect", "enabled", "enabled_all_activated"]
        else "32",
    )
    if case == "enabled_all_activated":
        ActivatedService.objects.create(user=user, service=Service.PILOTAGE)
        ActivatedService.objects.create(user=user, service=Service.MON_RECAP)
        NexusUserFactory(email=user.email, source=Service.DORA)
        NexusUserFactory(email=user.email, source=Service.MARCHE)
    client.force_login(user)
    response = client.get(reverse("home:hp"), follow=True)
    soup = parse_response_to_soup(response)

    [offcanvasNav] = soup.select("#offcanvasNav")
    for a_tags in soup.find_all("a", attrs={"href": True}):
        if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
            a_tags["href"] = remove_static_hash(a_tags["href"])  # Normalize href for CI
    set_org_id_for_snapshot(offcanvasNav)
    assert pretty_indented(offcanvasNav) == snapshot
