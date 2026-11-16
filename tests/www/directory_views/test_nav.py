import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import DirectoryActiveCity
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyMembershipFactory


@pytest.mark.parametrize(
    "active,assertion",
    [pytest.param(True, assertContains, id="active"), pytest.param(False, assertNotContains, id="inactive")],
)
def test_directory_nav_visibility_experimentation(active, assertion, client):
    vannes = create_city_vannes()
    if active:
        DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user

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
