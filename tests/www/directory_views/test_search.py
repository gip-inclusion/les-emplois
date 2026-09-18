from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateUsed

from itou.cities.models import DirectoryActiveCity
from itou.companies.enums import CompanyKind
from itou.nexus.enums import NexusStructureKind
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.www.directory_views.helpers import setup_directory


def test_access_is_restricted(client):
    response = client.get(reverse("directory:people_results"))
    assert response.status_code == 302

    client.force_login(JobSeekerFactory())
    response = client.get(reverse("directory:people_results"))
    assert response.status_code == 403


def test_active_city_is_required(client):
    user = EmployerFactory()
    client.force_login(user)

    response = client.get(reverse("directory:people_results"))

    assert response.status_code == 403


def test_access_requires_organization_coords(client):
    city = create_city_vannes()
    DirectoryActiveCity.objects.create(city=city)
    user = EmployerFactory(membership=False)
    CompanyMembershipFactory(user=user, company=CompanyFactory(coords=None, insee_city=city))
    client.force_login(user)

    response = client.get(reverse("directory:people_results"))

    assert response.status_code == 403


def test_people_search_filters_and_htmx(client):
    setup_directory(client)

    response = client.get(
        reverse("directory:people_results"),
        {"q": "Alice", "contacts": "phone"},
        headers={"HX-Request": "true"},
    )

    assertContains(response, "Alice Martin")
    assertContains(response, "Personne (1)")
    assertContains(response, "Mission locale de Vannes")
    assertContains(response, "Gestionnaire de structure")
    assertTemplateUsed(response, "directory/includes/people_results.html")


def test_people_search_restores_query_from_url(client):
    setup_directory(client)

    response = client.get(
        reverse("directory:people_results"),
        {"q": "Alice", "types": NexusStructureKind.ML, "contacts": "phone"},
    )

    assert response.status_code == 200
    assert response.context["form"]["q"].value() == "Alice"
    assert response.context["form"]["types"].value() == [NexusStructureKind.ML]
    assert response.context["form"]["contacts"].value() == ["phone"]
    assertContains(response, 'id="q-personnes"')


def test_people_search_matches_hyphenated_name(client):
    city = create_city_vannes()
    DirectoryActiveCity.objects.create(city=city)
    current_user = EmployerFactory(membership=False)
    CompanyMembershipFactory(user=current_user, company=CompanyFactory(coords=city.coords, insee_city=city))
    target = PrescriberFactory(
        membership=False,
        first_name="Jean-Philippe",
        last_name="Martin",
        email="jean-philippe@example.com",
        phone="0601020304",
    )
    PrescriberMembershipFactory(
        user=target,
        organization=PrescriberOrganizationFactory(coords=city.coords, insee_city=city),
    )
    client.force_login(current_user)

    response = client.get(reverse("directory:people_results"), {"q": "Jean Philippe"})

    assertContains(response, "Jean-Philippe Martin")


def test_people_search_filters_by_structure_type(client):
    _, _, _, city = setup_directory(client)
    employer = EmployerFactory(membership=False, first_name="Bob", last_name="Durand")
    CompanyMembershipFactory(
        user=employer,
        company=CompanyFactory(kind=CompanyKind.EI, coords=city.coords, insee_city=city, name="Atelier EI"),
    )

    response = client.get(reverse("directory:people_results"), {"types": NexusStructureKind.EI})

    assertContains(response, "Bob Durand")
    assertNotContains(response, "Alice Martin")


def test_directory_nav_is_visible_for_flagged_city(client):
    setup_directory(client)

    response = client.get(reverse("dashboard:index"))

    assertContains(response, "Annuaire pro")
