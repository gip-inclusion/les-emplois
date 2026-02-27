from functools import partial

import pytest
from django.urls import reverse

from itou.nexus.enums import Service
from itou.nexus.models import ActivatedService
from itou.users.enums import IdentityProvider
from tests.nexus.factories import NexusUserFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented, remove_static_hash


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
        pytest.param(PrescriberFactory, id="PrescriberWithoutOrganization"),
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

    def set_org_id_for_snapshot(soup):
        structure_switcher_buttons = soup.find_all("button", {"class": "active", "name": "organization_id"})
        if structure_switcher_buttons:
            [structure_switcher_button] = structure_switcher_buttons
            structure_switcher_button["value"] = "ORGANIZATION_ID"

    [nav_primary] = soup.select("#nav-primary")
    set_org_id_for_snapshot(nav_primary)
    assert pretty_indented(nav_primary) == snapshot(name="user menu")

    [offcanvasNav] = soup.select("#offcanvasNav")
    for a_tags in soup.find_all("a", attrs={"href": True}):
        if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
            a_tags["href"] = remove_static_hash(a_tags["href"])  # Normalize href for CI
    set_org_id_for_snapshot(offcanvasNav)
    assert pretty_indented(offcanvasNav) == snapshot(name="navigation")


@pytest.mark.parametrize("case", ["disabled", "enabled_no_proconnect", "enabled", "enabled_all_activated"])
def test_nexus_dropdown(snapshot, client, case, pro_connect):
    user = PrescriberFactory(
        for_snapshot=True,
        identity_provider=IdentityProvider.DJANGO if case == "enabled_no_proconnect" else IdentityProvider.PRO_CONNECT,
    )
    if case in ["enabled_no_proconnect", "enabled", "enabled_all_activated"]:
        PrescriberMembershipFactory(
            user=user,
            organization__name="On vous aide",
            organization__siret="012345678910",
            organization__post_code="31",
        )
    if case == "enabled_all_activated":
        ActivatedService.objects.create(user=user, service=Service.PILOTAGE)
        ActivatedService.objects.create(user=user, service=Service.MON_RECAP)
        NexusUserFactory(email=user.email, source=Service.DORA)
        NexusUserFactory(email=user.email, source=Service.MARCHE)
    client.force_login(user)
    response = client.get(reverse("home:hp"), follow=True)
    soup = parse_response_to_soup(response)

    def set_org_id_for_snapshot(soup):
        structure_switcher_buttons = soup.find_all("button", {"class": "active", "name": "organization_id"})
        if structure_switcher_buttons:
            [structure_switcher_button] = structure_switcher_buttons
            structure_switcher_button["value"] = "ORGANIZATION_ID"

    [offcanvasNav] = soup.select("#offcanvasNav")
    for a_tags in soup.find_all("a", attrs={"href": True}):
        if a_tags["href"].startswith("/static/pdf/syntheseSecurite"):
            a_tags["href"] = remove_static_hash(a_tags["href"])  # Normalize href for CI
    set_org_id_for_snapshot(offcanvasNav)
    assert pretty_indented(offcanvasNav) == snapshot
