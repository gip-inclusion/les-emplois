import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import DirectoryActiveCity
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory


@pytest.mark.parametrize(
    "directory_active,make_user,assertion",
    [
        pytest.param(
            True,
            lambda city: CompanyMembershipFactory(company__coords=city.coords, company__insee_city=city).user,
            assertContains,
            id="active-employer",
        ),
        pytest.param(
            True,
            lambda city: CompanyMembershipFactory(company__coords=city.coords).user,
            assertNotContains,
            id="active-employer-no-insee-city",
        ),
        pytest.param(
            True,
            lambda city: CompanyMembershipFactory(company__insee_city=city).user,
            assertNotContains,
            id="active-employer-no-coords",
        ),
        pytest.param(
            True,
            lambda city: (
                PrescriberMembershipFactory(
                    organization__coords=city.coords,
                    organization__insee_city=city,
                    organization__authorized=True,
                ).user
            ),
            assertContains,
            id="active-prescriber-authorized",
        ),
        pytest.param(
            True,
            lambda city: (
                PrescriberMembershipFactory(
                    organization__coords=city.coords,
                    organization__insee_city=city,
                ).user
            ),
            assertNotContains,
            id="active-prescriber-not-authorized",
        ),
        pytest.param(
            True,
            lambda city: (
                PrescriberMembershipFactory(
                    organization__coords=city.coords,
                    organization__authorized=True,
                ).user
            ),
            assertNotContains,
            id="active-prescriber-no-insee-city",
        ),
        pytest.param(
            True,
            lambda city: (
                PrescriberMembershipFactory(
                    organization__insee_city=city,
                    organization__authorized=True,
                ).user
            ),
            assertNotContains,
            id="active-prescriber-no-coords",
        ),
        pytest.param(
            True,
            lambda city: (
                InstitutionMembershipFactory(institution__coords=city.coords, institution__insee_city=city).user
            ),
            assertNotContains,
            id="active-labor-inspector",
        ),
        pytest.param(
            False,
            lambda city: CompanyMembershipFactory(company__coords=city.coords, company__insee_city=city).user,
            assertNotContains,
            id="inactive",
        ),
    ],
)
def test_directory_nav_visibility_experimentation(assertion, client, directory_active, make_user):
    vannes = create_city_vannes()
    if directory_active:
        DirectoryActiveCity.objects.create(city=vannes)
    user = make_user(vannes)

    client.force_login(user)
    response = client.get(reverse("dashboard:index"))

    assertion(
        response,
        """
        <li class="nav-item">
            <a href="/directory/" class="nav-link">
                <i class="ri-contacts-book-line fw-medium" aria-hidden="true"></i>
                <span>Annuaire pro</span>
                <span class="badge rounded-pill bg-important-lighter text-important badge-sm ms-2">
                    <i class="ri-flask-line" aria-hidden="true"></i>
                    Beta
                </span>
            </a>
        </li>
        """,
        html=True,
    )
