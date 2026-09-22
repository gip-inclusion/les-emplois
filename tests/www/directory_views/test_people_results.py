import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import City, DirectoryActiveCity
from itou.directory.models import DirectoryProfile
from tests.cities.factories import create_city_geispolsheim, create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import ProfessionalFactory
from tests.utils.testing import parse_response_to_soup
from tests.www.directory_views.utils import KM, coords_within_directory_radius


OTHER_STRUCTURE_TEXT = "+ 1 autre structure"


def test_display_other_organization(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = ProfessionalFactory(first_name="Alice", last_name="Martin")
    CompanyMembershipFactory(
        user=user,
        # The closest, sorts first and is the displayed organization.
        company__coords=vannes.coords,
        company__for_snapshot=True,
        company__insee_city=vannes,
        company__brand="Les petits paniers",
    )
    CompanyMembershipFactory(
        user=user,
        company__coords=coords_within_directory_radius(vannes.coords),
        company__insee_city=vannes,
        company__brand="Les grands paniers",
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(response, OTHER_STRUCTURE_TEXT)
    page = parse_response_to_soup(response, ".c-box--results")
    assert page.prettify() == snapshot(name="affiche 'Les petits paniers + 1 autre structure'")


def test_only_organizations_within_radius(client):
    geispolsheim = create_city_geispolsheim()
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = ProfessionalFactory(first_name="Alice", last_name="Martin")
    near_name = "Near company"
    far_name = "Far company"
    CompanyMembershipFactory(
        user=user,
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__brand=near_name,
    )
    CompanyMembershipFactory(
        user=user,
        company__coords=geispolsheim.coords,
        company__insee_city=geispolsheim,
        company__brand=far_name,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertNotContains(response, OTHER_STRUCTURE_TEXT)
    assertContains(
        response,
        f"""
        <li>
            <small>Structure</small>
            <strong>{near_name}</strong>
        </li>
        """,
        html=True,
        count=1,
    )


def test_organization_ordering(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = ProfessionalFactory(first_name="Alice", last_name="Martin")
    CompanyMembershipFactory(
        user=user,
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__brand="Les petits paniers",
    )
    CompanyMembershipFactory(
        user=user,
        company__coords=Point(vannes.coords.x - KM, vannes.coords.y - KM),
        company__insee_city=vannes,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(
        response,
        f"""
        <li>
            <small>Structure</small>
            <strong>Les petits paniers ({OTHER_STRUCTURE_TEXT})</strong>
        </li>
        """,
        html=True,
        count=1,
    )


def test_exclude_opted_out_email_and_distant_organization(client):
    geispolsheim = create_city_geispolsheim()
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    CompanyMembershipFactory(
        company__coords=geispolsheim.coords,
        company__insee_city=geispolsheim,
    )
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user
    DirectoryProfile.objects.create(user=user, is_opted_out=True)

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(response, '<p class="mb-0">Annuaire vide.</p>', count=1)


def test_directory_people_ignores_inactive_companies(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    CompanyFactory(
        subject_to_iae_rules=True,
        convention__is_active=False,
        coords=vannes.coords,
        insee_city=vannes,
        with_membership=True,
    )
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user
    DirectoryProfile.objects.create(user=user, is_opted_out=True)

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(response, '<p class="mb-0">Annuaire vide.</p>', count=1)


def test_ordering_and_pagination(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    for i in range(10):
        # Alphabetical ordering should not pass the test.
        letter = "A" if i % 2 == 0 else "M"
        suffix = chr(i // 2 + ord(letter))
        CompanyMembershipFactory(
            company__coords=Point(vannes.coords.x + i * KM, vannes.coords.y + i * KM),
            company__insee_city=vannes,
            user__last_name=f"{suffix}",
            user__first_name=f"{suffix}",
        )
    user = CompanyMembershipFactory(
        company__coords=Point(vannes.coords.x + (i + 1) * KM, vannes.coords.y + (i + 1) * KM),
        company__insee_city=vannes,
        user__first_name="Z second page",
        user__last_name="Z second page",
    ).user

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    page = parse_response_to_soup(response)
    [pagination] = page.select("ul.pagination")
    assert pagination.prettify() == snapshot()
    people_with_markup = page.find_all("h3")
    people = [node.string.strip() for node in people_with_markup]
    assert people == ["A A", "B B", "C C", "D D", "E E", "M M", "N N", "O O", "P P", "Q Q"]


def test_people_search_includes_nearby_other_city(client):
    vannes = create_city_vannes()
    arradon = City.objects.create(
        name="Arradon",
        slug="arradon-56",
        department="56",
        coords=Point(-2.823008, 47.627922),
        post_codes=["56610"],
        code_insee="56003",
    )
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user
    PrescriberMembershipFactory(
        user__first_name="Claire",
        user__last_name="Dupont",
        organization__coords=arradon.coords,
        organization__insee_city=arradon,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(response, "<h3>DUPONT Claire</h3>", count=1)


@pytest.mark.parametrize(
    "active,assertion",
    [pytest.param(True, assertContains, id="active"), pytest.param(False, assertNotContains, id="inactive")],
)
def test_directory_nav_visibility(active, assertion, client):
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
            <a href="/annuaire/" class="nav-link">
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
