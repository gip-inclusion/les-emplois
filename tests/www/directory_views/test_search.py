from django.conf import settings
from django.contrib.gis.geos import Point
from django.templatetags.static import static
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects, assertTemplateUsed

from itou.cities.models import City, DirectoryActiveCity
from itou.companies.enums import CompanyKind
from itou.nexus.enums import NexusStructureKind
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.testing import update_page_with_htmx
from tests.utils.testing import parse_response_to_soup
from tests.www.directory_views.helpers import get_target_person, setup_directory


def test_access_is_restricted(client):
    response = client.get(reverse("directory:people_results"))
    assertRedirects(response, f"{reverse('account_login')}?next={reverse('directory:people_results')}")

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
    _, _, _, person = get_target_person(client)
    page = parse_response_to_soup(client.get(reverse("directory:people_results"), {"q": person.public_id}))

    response = client.get(
        reverse("directory:people_results"),
        {"q": person.public_id},
        headers={"HX-Request": "true"},
    )

    update_page_with_htmx(page, "#people-search-form", response)
    assert [heading.text for heading in page.select("#people-search-results h3")] == ["Alice Martin"]
    assert page.select_one(f'#people-search-form select[name="q"] option[value="{person.public_id}"][selected]')
    assert page.select_one("#people-search-count")
    assert page.select_one('#people-search-form input[name="types"]')
    assertTemplateUsed(response, "directory/includes/people_results.html")
    assertNotContains(response, "js/directory_feedback.js")


def test_people_search_restores_query_from_url(client):
    _, _, _, person = get_target_person(client)

    response = client.get(
        reverse("directory:people_results"),
        {"q": person.public_id, "types": NexusStructureKind.ML},
    )

    page = parse_response_to_soup(response)
    assert page.select_one(f'select[name="q"] option[value="{person.public_id}"][selected]')
    assert page.select_one(f'input[name=types][value="{NexusStructureKind.ML}"]').has_attr("checked")
    assertContains(response, static("js/directory_feedback.js"))
    assertContains(response, "Annuaire Pro en accès bêta restreint")
    assertContains(response, "Vous faites partie des premiers à accéder à cette fonctionnalité")
    assertContains(response, reverse("dashboard:edit_user_info"))
    assertContains(response, 'id="people-clear-filters"')
    assert page.select_one("#people-search-form")["hx-trigger"] == "change delay:300ms"


def test_people_search_has_hidden_clear_button_without_filters(client):
    setup_directory(client)

    response = client.get(reverse("directory:people_results"))

    assertContains(response, 'id="people-clear-filters"')
    assert "d-none" in parse_response_to_soup(response).select_one("#people-clear-filters")["class"]


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
    setup_directory(client)
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
    response = client.get(reverse("directory:people_results"))
    assertContains(response, "<h3>Claire Dupont</h3>", count=1)


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
    company = CompanyFactory(coords=city.coords, insee_city=city)
    CompanyMembershipFactory(user=target, company=company)

    response = client.get(reverse("directory:people_results"))
    assertContains(response, f"<strong>{company.display_name} (+ 1 autres structures)</strong>", html=True, count=1)


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
