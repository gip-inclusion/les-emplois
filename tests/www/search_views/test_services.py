import random
from functools import partial

import pytest
from data_inclusion.schema import v1 as data_inclusion_v1
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiException
from tests.cities.factories import create_city_vannes
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, parse_response_to_soup, pretty_indented


@pytest.fixture(name="search_services_route")
def search_services_route_fixture(respx_mock, settings):
    items = [
        {
            "service": {
                "id": "dora-distanciel-vannes",
                "source": "dora",
                "nom": "Coupe les cheveux",
                "modes_accueil": [data_inclusion_v1.ModeAccueil.A_DISTANCE],
                "lien_source": f"{settings.DORA_BASE_URL}/services/dora-distanciel-vannes",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "56260",
                "longitude": -2.8186843,
                "latitude": 47.657641,
                "description": "Coupe les cheveux longs",
            },
        },
        {
            "service": {
                "id": "dora-presentiel-vannes",
                "source": "dora",
                "nom": "Coupe également les cheveux",
                "modes_accueil": [data_inclusion_v1.ModeAccueil.EN_PRESENTIEL],
                "lien_source": f"{settings.DORA_BASE_URL}/services/dora-presentiel-vannes",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "56260",
                "longitude": -2.8186843,
                "latitude": 47.657641,
                "description": "Coupe également les cheveux longs",
            },
        },
        {
            "service": {
                "id": "autre-presentiel-vannes",
                "source": "autre",
                "nom": "Coupe que les cheveux",
                "modes_accueil": [data_inclusion_v1.ModeAccueil.EN_PRESENTIEL],
                "structure": {"nom": "Coiffeur"},
                "code_postal": "56260",
                "longitude": -2.8186843,
                "latitude": 47.657641,
                "description": "Coupe que les cheveux longs",
            },
        },
        {
            "service": {
                "id": "autre-distanciel-geispolsheim",
                "source": "autre",
                "nom": "Coupe que les cheveux",
                "modes_accueil": [data_inclusion_v1.ModeAccueil.A_DISTANCE],
                "structure": {"nom": "Coiffeur"},
                "code_postal": "67152",
                "longitude": 7.644817,
                "latitude": 48.515883,
                "description": "Coupe que les cheveux longs",
            },
        },
        {
            "service": {
                "id": "dora-geispolsheim",
                "source": "dora",
                "nom": "Coupe tout les cheveux",
                "modes_accueil": list(data_inclusion_v1.ModeAccueil),
                "lien_source": f"{settings.DORA_BASE_URL}/services/dora-vannes",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "67152",
                "longitude": 7.644817,
                "latitude": 48.515883,
                "description": "Coupe tout les cheveux longs",
            },
        },
        {
            "service": {
                "id": "autre-none-nowhere",
                "source": "autre",
                "nom": "Coupe entre autres les cheveux",
                "modes_accueil": None,
                "structure": {"nom": "Coiffeur"},
                "description": "Coupe entre autres les cheveux longs",
            },
        },
    ]
    random.shuffle(items)
    return respx_mock.route(url=f"{global_constants.API_DATA_INCLUSION_BASE_URL}/api/v1/search/services").respond(
        json={"items": items},
    )


def test_home_anonymous(client):
    response = client.get(reverse("search:services_home"))
    assertContains(response, "Rechercher un service d'insertion")


def test_home_connected(client):
    user_factory = random.choice([EmployerFactory, PrescriberFactory])
    client.force_login(user_factory(membership=True))

    with pytest.warns(RuntimeWarning, match="Access to 'search_services_home' while authenticated"):
        response = client.get(reverse("search:services_home"))
    assertRedirects(response, reverse("search:services_results"))


def test_invalid_query_parameters(client):
    response = client.get(reverse("search:services_results"), {"city": "foo-44", "category": "foobar"})
    assertContains(response, "Rechercher un service d'insertion")
    assertContains(response, "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.")


def test_results_html(snapshot, client, search_services_route):
    expected_items = 6
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assertContains(response, f"{expected_items} résultats")
    assertContains(
        response,
        f"<title>Services d'insertion « {category.label} » autour de {city} - Les emplois de l'inclusion</title>",
        html=True,
        count=1,
    )
    assertContains(response, "Voir la fiche détaillée", count=expected_items)
    assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot()


@pytest.mark.parametrize(
    "user_factory",
    [
        pytest.param(None, id="anonymous"),
        pytest.param(JobSeekerFactory, id="jobseeker"),
        pytest.param(partial(EmployerFactory, membership=True), id="employer"),
        pytest.param(partial(PrescriberFactory, membership=True), id="prescriber"),
        pytest.param(partial(LaborInspectorFactory, membership=True), id="labor_inspector"),
        pytest.param(ItouStaffFactory, id="itou_staff"),
    ],
)
def test_results_html_link(snapshot, client, search_services_route, user_factory):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    if user_factory:
        client.force_login(user_factory())
    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert (
        pretty_indented(
            parse_response_to_soup(response, selector="#services-search-results > .c-box--results:first-child a")
        )
        == snapshot()
    )


def test_results_ordering(client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert [service["id"] for service in response.context["results"].object_list] == [
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "dora-geispolsheim",
        "dora-distanciel-vannes",
        "autre-distanciel-geispolsheim",
        "autre-none-nowhere",
    ]


def test_results_are_cached(client, search_services_route):
    city = create_city_vannes()

    client.get(reverse("search:services_results"), {"city": city.slug, "category": data_inclusion_v1.Categorie.SANTE})
    assert search_services_route.call_count == 1
    # A subsequent call with the same query should be cached
    client.get(reverse("search:services_results"), {"city": city.slug, "category": data_inclusion_v1.Categorie.SANTE})
    assert search_services_route.call_count == 1
    # With a different query a new request should be issued
    client.get(
        reverse("search:services_results"), {"city": city.slug, "category": data_inclusion_v1.Categorie.MOBILITE}
    )
    assert search_services_route.call_count == 2


def test_api_error(snapshot, client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    search_services_route.side_effect = DataInclusionApiException
    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot()

    # Make a second call to check the results were cached
    assert search_services_route.call_count == 1
    client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert search_services_route.call_count == 1


def test_pagination(settings, client, search_services_route):
    settings.PAGE_SIZE_SMALL = 1
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    url = reverse("search:services_results", query={"city": city.slug, "category": category})
    assertContains(client.get(url), PAGINATION_PAGE_ONE_MARKUP % (url + "&page=1"), html=True)


def test_htmx_reload_for_filters(client, htmx_client, search_services_route):
    vannes = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))
    url = reverse("search:services_results")

    simulated_page = parse_response_to_soup(
        client.get(
            url, {"city": vannes.slug, "category": category, "receptions": data_inclusion_v1.ModeAccueil.EN_PRESENTIEL}
        )
    )
    [checkbox_input] = simulated_page.find_all(
        "input",
        attrs={"type": "checkbox", "name": "receptions", "value": data_inclusion_v1.ModeAccueil.A_DISTANCE},
    )
    checkbox_input["checked"] = ""
    [checkbox_input] = simulated_page.find_all(
        "input",
        attrs={"type": "checkbox", "name": "receptions", "value": data_inclusion_v1.ModeAccueil.EN_PRESENTIEL},
    )
    del checkbox_input.attrs["checked"]
    update_page_with_htmx(
        simulated_page,
        f"form[hx-get='{url}']",
        htmx_client.get(
            url, {"city": vannes.slug, "category": category, "receptions": data_inclusion_v1.ModeAccueil.A_DISTANCE}
        ),
    )

    response = client.get(
        url, {"city": vannes.slug, "category": category, "receptions": data_inclusion_v1.ModeAccueil.A_DISTANCE}
    )
    fresh_page = parse_response_to_soup(response)

    assertSoupEqual(simulated_page, fresh_page)
