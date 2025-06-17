import pytest
from django.conf import settings

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.immersion_facile import get_pmsmp_url, immersion_search_url
from tests.companies.factories import CompanyFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory


def test_immersion_search_url():
    user = JobSeekerFactory(
        post_code="58160",
        city="Sauvigny-les-Bois",
        with_geoloc=True,
    )
    expected_url = (
        f"{settings.IMMERSION_FACILE_SITE_URL}/recherche?"
        f"mtm_campaign=les-emplois-recherche-immersion"
        f"&mtm_kwd=les-emplois-recherche-immersion"
        f"&distanceKm=20"
        f"&latitude=0.0&longitude=0.0"
        f"&sortedBy=distance"
        f"&place=Sauvigny-les-Bois%2C%20Bourgogne-Franche-Comt%C3%A9%2C%20France"
    )
    assert immersion_search_url(user) == expected_url

    user = JobSeekerFactory(without_geoloc=True)
    expected_url = (
        f"{settings.IMMERSION_FACILE_SITE_URL}/recherche?"
        f"mtm_campaign=les-emplois-recherche-immersion"
        f"&mtm_kwd=les-emplois-recherche-immersion"
    )
    assert immersion_search_url(user) == expected_url


@pytest.mark.parametrize(
    "organization_kind,organization_kind_param",
    [
        (PrescriberOrganizationKind.FT, "pole-emploi"),
        (PrescriberOrganizationKind.ML, "mission-locale"),
        (PrescriberOrganizationKind.CAP_EMPLOI, "cap-emploi"),
        (PrescriberOrganizationKind.CCAS, "autre"),
    ],
)
def test_get_pmsmp_url(organization_kind, organization_kind_param):
    prescriber_organization = PrescriberOrganizationFactory(authorized=True, kind=organization_kind)
    to_company = CompanyFactory()

    expected_url = (
        f"{settings.IMMERSION_FACILE_SITE_URL}/demande-immersion"
        f"?agencyDepartment={prescriber_organization.department}"
        f"&agencyKind={organization_kind_param}&siret={to_company.siret}"
        "&skipIntro=true&acquisitionCampaign=emplois&mtm_kwd=candidature"
    )

    assert get_pmsmp_url(prescriber_organization, to_company) == expected_url
