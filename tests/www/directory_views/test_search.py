from django.conf import settings
from django.contrib.gis.geos import Point
from django.templatetags.static import static
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import City
from itou.companies.enums import CompanyKind
from itou.nexus.enums import NexusStructureKind
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup
from tests.www.directory_views.helpers import get_target_person, setup_directory


def test_people_search_filters_and_htmx(client):
    _, _, target_organization, person = get_target_person(client)
    other_user = EmployerFactory(membership=False, first_name="Julie", last_name="Durand")
    company = CompanyFactory(
        coords=target_organization.coords,
        insee_city=target_organization.insee_city,
    )
    CompanyMembershipFactory(user=other_user, company=company)
    page = parse_response_to_soup(client.get(reverse("directory:people_results")))

    response = client.get(
        reverse("directory:people_results"),
        {"q": person.public_id},
        headers={"HX-Request": "true"},
    )

    update_page_with_htmx(page, "#people-search-form", response)
    assert [heading.text for heading in page.select("#people-search-results h3")] == ["MARTIN Alice"]
    [empty_option] = page.select('#people-search-form select[name="q"] option[value=""]')
    del empty_option["selected"]
    [option] = page.select(f'#people-search-form select[name="q"] option[value="{person.public_id}"]')
    option["selected"] = ""
    assertSoupEqual(
        page,
        parse_response_to_soup(client.get(reverse("directory:people_results"), {"q": person.public_id})),
    )


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
    assertContains(response, "<h3>DUPONT Claire</h3>", count=1)


def test_people_search_shows_nearest_structure_after_type_filter(client):
    _, target, _, city = setup_directory(client)
    CompanyMembershipFactory(
        user=target,
        company=CompanyFactory(kind=CompanyKind.EI, coords=Point(-2.75, 47.66), insee_city=city, name="Atelier EI"),
    )

    response = client.get(reverse("directory:people_results"), {"types": NexusStructureKind.EI})

    assertContains(response, "MARTIN Alice")
    assertContains(response, "Mission locale de Vannes")
    assertNotContains(response, "Atelier EI")


def test_people_search_displays_membership_count(client):
    _, target, _, city = setup_directory(client)
    company = CompanyFactory(
        coords=city.coords,
        insee_city=city,
        # Sorts before Mission Locale de Vannes.
        name="Les petits paniers",
    )
    CompanyMembershipFactory(user=target, company=company)

    response = client.get(reverse("directory:people_results"))
    assertContains(response, "<strong>Les petits paniers (+ 1 autre structure)</strong>", html=True, count=1)


def test_directory_nav_is_visible_for_flagged_city(client):
    setup_directory(client)

    response = client.get(reverse("dashboard:index"))

    assertContains(response, "Annuaire pro")
