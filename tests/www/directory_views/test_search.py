from django.conf import settings
from django.contrib.gis.geos import Point
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateUsed

from itou.cities.models import City, DirectoryActiveCity
from itou.companies.enums import CompanyKind
from itou.nexus.enums import NexusStructureKind
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.www.directory_views.helpers import get_target_person, setup_directory


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
        {"q": "Alice"},
        headers={"HX-Request": "true"},
    )

    assertContains(response, "Alice Martin")
    assertContains(response, "Personne (1)")
    assertContains(response, "Mission locale de Vannes")
    assertContains(response, "Gestionnaire de structure")
    assertContains(response, "ri-map-pin-2-line")
    assertContains(response, "ri-eye-line")
    assertTemplateUsed(response, "directory/includes/people_results.html")
    assertNotContains(response, "js/directory_feedback.js")


def test_people_search_restores_query_from_url(client):
    setup_directory(client)

    response = client.get(
        reverse("directory:people_results"),
        {"q": "Alice", "types": NexusStructureKind.ML},
    )

    assert response.status_code == 200
    assert response.context["form"]["q"].value() == "Alice"
    assert response.context["form"]["types"].value() == [NexusStructureKind.ML]
    assertContains(response, 'id="q-personnes"')
    assertContains(response, "js/directory_feedback.js")
    assertContains(response, "Annuaire Pro en accès bêta restreint")
    assertContains(response, "Vous faites partie des premiers à accéder à cette fonctionnalité")
    assertContains(response, reverse("dashboard:edit_user_info"))
    assertContains(response, 'class="btn btn-sm btn-outline-primary has-external-link"')
    assertContains(response, 'id="people-clear-filters"')
    assertNotContains(response, "ms-lg-auto d-none")


def test_people_search_has_hidden_clear_button_without_filters(client):
    setup_directory(client)

    response = client.get(reverse("directory:people_results"))

    assertContains(response, 'id="people-clear-filters"')
    assertContains(response, "ms-lg-auto d-none")


def test_people_search_pagination_replaces_results_container(client, mocker):
    _, _, _, person = get_target_person(client)
    mocker.patch(
        "itou.www.directory_views.views.get_directory_people",
        return_value=[person] * (settings.PAGE_SIZE_SMALL + 1),
    )

    response = client.get(reverse("directory:people_results"))

    assertContains(response, 'hx-target="#people-search-results"')
    assertContains(response, 'hx-swap="outerHTML"')


def test_people_search_includes_nearby_other_city(client):
    _, _, _, city = setup_directory(client)
    neighboring_city = City.objects.create(
        name="Ville voisine",
        slug="ville-voisine-56",
        department="56",
        coords=Point(-2.75, 47.66),
        post_codes=["56001"],
        code_insee="56001",
    )
    neighbor = PrescriberFactory(membership=False, first_name="Claire", last_name="Dupont")
    PrescriberMembershipFactory(
        user=neighbor,
        organization=PrescriberOrganizationFactory(coords=neighboring_city.coords, insee_city=neighboring_city),
    )

    response = client.get(reverse("directory:people_results"), {"q": "Claire"})

    assertContains(response, "Claire Dupont")


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


def test_people_search_shows_nearest_structure_after_type_filter(client):
    _, target, _, city = setup_directory(client)
    CompanyMembershipFactory(
        user=target,
        company=CompanyFactory(kind=CompanyKind.EI, coords=Point(-2.75, 47.66), insee_city=city, name="Atelier EI"),
    )

    response = client.get(reverse("directory:people_results"), {"types": NexusStructureKind.EI})

    assertContains(response, "Alice Martin")
    assertContains(response, "Mission locale de Vannes")
    assertNotContains(response, "Atelier EI")


def test_people_search_displays_membership_count(client):
    _, target, _, city = setup_directory(client)
    CompanyMembershipFactory(user=target, company=CompanyFactory(coords=city.coords, insee_city=city))

    response = client.get(reverse("directory:people_results"), {"q": "Alice"})

    assertContains(response, "Membre de 2 structures")


def test_directory_nav_is_visible_for_flagged_city(client):
    setup_directory(client)

    response = client.get(reverse("dashboard:index"))

    assertContains(response, "Annuaire pro")


def test_directory_nav_skips_active_cities_lookup_without_insee_city(client, mocker):
    user = EmployerFactory(membership=False)
    CompanyMembershipFactory(user=user, company=CompanyFactory(coords=Point(-2.75, 47.66), insee_city=None))
    client.force_login(user)
    active_cities = mocker.patch("itou.utils.templatetags.nav.get_directory_active_city_ids")

    response = client.get(reverse("dashboard:index"))

    active_cities.assert_not_called()
    assertNotContains(response, reverse("directory:people_results"))
