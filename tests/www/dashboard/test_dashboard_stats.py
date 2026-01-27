import random

import pytest
from django.urls import reverse

from itou.companies.enums import CompanyKind
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.www.stats.utils import STATS_PH_ORGANISATION_KIND_WHITELIST
from tests.institutions.factories import LaborInspectorFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented
from tests.www.stats.test_views import has_activated_pilotage_in_nexus


@pytest.mark.parametrize(
    "kind",
    [CompanyKind.GEIQ] + CompanyKind.siae_kinds(),
)
def test_index_stats_for_employer(snapshot, client, kind):
    employer = EmployerFactory(
        membership=True,
        membership__company__kind=kind,
    )
    client.force_login(employer)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert has_activated_pilotage_in_nexus(employer)


def test_index_stats_for_authorized_prescriber(snapshot, client):
    possible_kinds = (
        set(PrescriberOrganizationKind)
        - set(STATS_PH_ORGANISATION_KIND_WHITELIST)
        - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.DEPT}  # Custom layout
        - {PrescriberOrganizationKind.OTHER}  # Can't be authorized
    )
    prescriber = PrescriberFactory(
        membership__organization__authorized=True,
        membership__organization__kind=random.choice(list(possible_kinds)),
    )
    client.force_login(prescriber)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert has_activated_pilotage_in_nexus(prescriber)


@pytest.mark.parametrize("kind", STATS_PH_ORGANISATION_KIND_WHITELIST)
def test_index_stats_for_authorized_prescriber_whitelist(snapshot, client, kind):
    prescriber = PrescriberFactory(
        membership__organization__authorized=True,
        membership__organization__kind=kind,
    )
    client.force_login(prescriber)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert has_activated_pilotage_in_nexus(prescriber)


@pytest.mark.parametrize("kind", {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.DEPT})
def test_index_stats_for_authorized_prescriber_with_custom_layout(snapshot, client, kind):
    prescriber = PrescriberFactory(
        membership__organization__authorized=True,
        membership__organization__kind=kind,
    )
    client.force_login(prescriber)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert has_activated_pilotage_in_nexus(prescriber)


def test_index_stats_for_non_authorized_prescriber(snapshot, client):
    prescriber = PrescriberFactory(
        membership__organization__authorized=False, membership__organization__kind=PrescriberOrganizationKind.OTHER
    )
    client.force_login(prescriber)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert has_activated_pilotage_in_nexus(prescriber)


@pytest.mark.parametrize("kind", InstitutionKind)
def test_index_stats_for_labor_inspector(snapshot, client, kind):
    labor_inspector = LaborInspectorFactory(membership__institution__kind=kind)
    client.force_login(labor_inspector)

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()

    assert not has_activated_pilotage_in_nexus(labor_inspector)
