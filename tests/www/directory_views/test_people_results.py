from django.contrib.gis.geos import Point
from django.urls import reverse
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import City, DirectoryActiveCity
from itou.directory.models import DirectoryProfile
from tests.cities.factories import create_city_geispolsheim, create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import ProfessionalFactory
from tests.utils.testing import parse_response_to_soup
from tests.www.directory_views.utils import KM, coords_within_directory_radius


OTHER_STRUCTURE_TEXT = "+ 1 autre structure"


def people_in_page(page):
    people_with_markup = page.find_all("h3")
    people = [node.string.strip() for node in people_with_markup]
    return people


def test_people_results(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        user__last_name="Employeur",
        user__first_name="A",
    ).user
    CompanyMembershipFactory(company__coords=vannes.coords, user__last_name="Employeur", user__first_name="B")
    for first_name in ["A", "B"]:
        PrescriberMembershipFactory(
            organization__coords=vannes.coords,
            organization__authorized=True,
            user__last_name="Prescripteur habilité",
            user__first_name=first_name,
        )
        PrescriberMembershipFactory(
            organization__coords=vannes.coords,
            user__last_name="Orienteur",
            user__first_name=first_name,
        )
    InstitutionMembershipFactory(
        institution__coords=vannes.coords,
        user__last_name="Inspecteur",
        user__first_name="A",
    )

    client.force_login(user)
    with assertSnapshotQueries(snapshot):
        response = client.get(reverse("directory:people_results"))

    page = parse_response_to_soup(response)
    people = people_in_page(page)
    assert len(people) == 6
    assert "EMPLOYEUR A" in people
    assert "EMPLOYEUR B" in people
    assert "PRESCRIPTEUR HABILITÉ A" in people
    assert "PRESCRIPTEUR HABILITÉ B" in people
    assert "ORIENTEUR A" in people
    assert "ORIENTEUR B" in people
    assert "INSPECTEUR A" not in people


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
    near_membership = CompanyMembershipFactory(
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

    [user_in_page] = response.context["results"]
    assert user_in_page.directory_memberships == [near_membership]
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


def test_exclude_opted_out_email(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user
    DirectoryProfile.objects.create(user=user, is_opted_out=True)

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assertContains(response, '<p class="mb-0">Annuaire vide.</p>', count=1)


def test_ignores_inactive_companies(client):
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

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    page = parse_response_to_soup(response)
    assert people_in_page(page) == [user.get_inverted_full_name()]


def test_alphabetical_ordering_and_pagination(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    for i in range(10):
        # Ordering by PK should not pass the test.
        letter = "A" if i % 2 == 0 else "M"
        name = chr(i // 2 + ord(letter))
        CompanyMembershipFactory(
            company__coords=Point(vannes.coords.x + i * KM, vannes.coords.y + i * KM),
            company__insee_city=vannes,
            user__last_name=name,
            user__first_name=name,
        )
    user = CompanyMembershipFactory(
        # Search point is farthest from Vannes.
        # Ordering by distance should not pass the test.
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
    assert people_in_page(page) == ["A A", "B B", "C C", "D D", "E E", "M M", "N N", "O O", "P P", "Q Q"]

    response = client.get(reverse("directory:people_results"), {"page": 2})
    assert people_in_page(parse_response_to_soup(response)) == ["Z SECOND PAGE Z Second Page"]


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

    assert "DUPONT Claire" in people_in_page(parse_response_to_soup(response))
