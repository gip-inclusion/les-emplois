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


@pytest.mark.parametrize(
    "kind",
    [CompanyKind.GEIQ] + CompanyKind.siae_kinds(),
)
def test_index_stats_for_employer(snapshot, client, kind):
    client.force_login(
        EmployerFactory(
            membership=True,
            membership__company__kind=kind,
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


def test_index_stats_for_authorized_prescriber(snapshot, client):
    possible_kinds = (
        set(PrescriberOrganizationKind)
        - set(STATS_PH_ORGANISATION_KIND_WHITELIST)
        - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.DEPT}  # Custom layout
        - {PrescriberOrganizationKind.OTHER}  # Can't be authorized
    )
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=True,
            membership__organization__kind=random.choice(list(possible_kinds)),
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


@pytest.mark.parametrize("kind", STATS_PH_ORGANISATION_KIND_WHITELIST)
def test_index_stats_for_authorized_prescriber_whitelist(snapshot, client, kind):
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=True,
            membership__organization__kind=kind,
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


@pytest.mark.parametrize("kind", {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.DEPT})
def test_index_stats_for_authorized_prescriber_with_custom_layout(snapshot, client, kind):
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=True,
            membership__organization__kind=kind,
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


def test_index_stats_for_non_authorized_prescriber(snapshot, client):
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=False, membership__organization__kind=PrescriberOrganizationKind.OTHER
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


@pytest.mark.parametrize("kind", InstitutionKind)
def test_index_stats_for_labor_inspector(snapshot, client, kind):
    client.force_login(LaborInspectorFactory(membership__institution__kind=kind))

    response = client.get(reverse("dashboard:index_stats"))
    assert pretty_indented(parse_response_to_soup(response, selector="#statistiques")) == snapshot()
