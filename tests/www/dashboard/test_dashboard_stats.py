import pytest
from django.urls import reverse

from itou.companies.enums import CompanyKind
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from tests.institutions.factories import LaborInspectorFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


@pytest.mark.parametrize("department", ["31", "84", "90"])
@pytest.mark.parametrize("kind", [CompanyKind.EI, CompanyKind.ACI])
def test_index_stats_for_employer(snapshot, client, kind, department):
    client.force_login(
        EmployerFactory(
            with_company=True,
            with_company__company__kind=kind,
            with_company__company__department=department,
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert str(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


@pytest.mark.parametrize("department", ["31", "75", "84", "90"])
@pytest.mark.parametrize(
    "kind",
    [
        PrescriberOrganizationKind.DEPT,
        PrescriberOrganizationKind.FT,
        PrescriberOrganizationKind.CHRS,
        PrescriberOrganizationKind.CHU,
        PrescriberOrganizationKind.OIL,
        PrescriberOrganizationKind.RS_FJT,
        PrescriberOrganizationKind.CAP_EMPLOI,
        PrescriberOrganizationKind.ML,
    ],
)
def test_index_stats_for_authorized_prescriber(snapshot, client, kind, department):
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=True,
            membership__organization__kind=kind,
            membership__organization__department=department,
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert str(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


def test_index_stats_for_non_authorized_prescriber(snapshot, client):
    client.force_login(
        PrescriberFactory(
            membership__organization__authorized=False, membership__organization__kind=PrescriberOrganizationKind.OTHER
        )
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert str(parse_response_to_soup(response, selector="#statistiques")) == snapshot()


@pytest.mark.parametrize("department", ["31", "84", "90"])
@pytest.mark.parametrize("kind", InstitutionKind)
def test_index_stats_for_labor_inspector(snapshot, client, kind, department):
    client.force_login(
        LaborInspectorFactory(membership__institution__kind=kind, membership__institution__department=department)
    )

    response = client.get(reverse("dashboard:index_stats"))
    assert str(parse_response_to_soup(response, selector="#statistiques")) == snapshot()
