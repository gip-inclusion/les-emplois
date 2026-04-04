import random
from functools import partial

import pytest
from data_inclusion.schema import v1 as data_inclusion_v1
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiException
from itou.www.search_views.forms import ServiceSearchForm
from tests.cities.factories import create_city_guerande, create_city_vannes
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
                "lien_source": f"{settings.DORA_WWW_BASE_URL}/services/dora-distanciel-vannes",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "56260",
                "commune": "Vannes",
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
                "lien_source": f"{settings.DORA_WWW_BASE_URL}/services/dora-presentiel-vannes",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "56260",
                "commune": "Vannes",
                "adresse": "Une adresse en présentiel à Vannes",
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
                "commune": "Vannes",
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
                "commune": "Geispolsheim",
                "longitude": 7.644817,
                "latitude": 48.515883,
                "description": "Coupe que les cheveux longs",
            },
        },
        {
            "service": {
                "id": "dora-geispolsheim",
                "source": "dora",
                "nom": "Coupe tous les cheveux",
                "modes_accueil": list(data_inclusion_v1.ModeAccueil),
                "lien_source": f"{settings.DORA_WWW_BASE_URL}/services/dora-geispolsheim",
                "structure": {"nom": "Coiffeur"},
                "code_postal": "67152",
                "commune": "Geispolsheim",
                "adresse": "Une adresse en présentiel et distanciel à Geispolsheim",
                "longitude": 7.644817,
                "latitude": 48.515883,
                "description": "Coupe tous les cheveux longs",
            },
        },
        {
            "service": {
                "id": "autre-presentiel-nowhere",
                "source": "autre",
                "nom": "Coupe aussi les cheveux",
                "modes_accueil": [data_inclusion_v1.ModeAccueil.EN_PRESENTIEL],
                "structure": {"nom": "Coiffeur"},
                "description": "Coupe aussi cheveux longs",
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
    expected_items = 7
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(
        reverse("search:services_results"),
        {"city": city.slug, "category": category, "reception": ServiceSearchForm.RECEPTION_ALL_VALUE},
    )
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


def test_results_html_with_zero_distance(snapshot, settings, client, search_services_route):
    guerande = create_city_guerande()
    search_services_route.respond(
        json={
            "items": [
                {
                    "service": {
                        "id": "dora-guerande",
                        "source": "dora",
                        "nom": "La boule à Zéro",
                        "modes_accueil": list(data_inclusion_v1.ModeAccueil),
                        "lien_source": f"{settings.DORA_WWW_BASE_URL}/services/dora-guerande",
                        "structure": {"nom": "Coiffeur"},
                        "code_postal": guerande.post_codes[0],
                        "commune": guerande.name,
                        "longitude": guerande.longitude,
                        "latitude": guerande.latitude,
                        "description": "Ne fait que des boules à zéro",
                    },
                }
            ]
        },
    )

    response = client.get(
        reverse("search:services_results"),
        {"city": guerande.slug, "category": random.choice(list(data_inclusion_v1.Categorie))},
    )
    assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot()


def test_results_ordering(client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(
        reverse("search:services_results"),
        {"city": city.slug, "category": category, "reception": ServiceSearchForm.RECEPTION_ALL_VALUE},
    )
    assert [service["id"] for service in response.context["results"].object_list] == [
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "dora-geispolsheim",
        "autre-presentiel-nowhere",
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


def test_filter_reception_strictness(client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))
    query_params = {"city": city.slug, "category": category}

    response = client.get(
        reverse("search:services_results"), {**query_params, "reception": data_inclusion_v1.ModeAccueil.EN_PRESENTIEL}
    )
    assert {service["id"] for service in response.context["results"].object_list} == {
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "dora-distanciel-vannes",  # Only here because of our mock, the production API would not have returned it
    }

    response = client.get(
        reverse("search:services_results"), {**query_params, "reception": data_inclusion_v1.ModeAccueil.A_DISTANCE}
    )
    assert {service["id"] for service in response.context["results"].object_list} == {
        "dora-geispolsheim",
        "dora-distanciel-vannes",
        "autre-distanciel-geispolsheim",
        # In production the following ones would have been filtered out,
        # keeping it in the mocked response to check missing value case.
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "autre-presentiel-nowhere",
        "autre-none-nowhere",
    }

    response = client.get(
        reverse("search:services_results"), {**query_params, "reception": ServiceSearchForm.RECEPTION_ALL_VALUE}
    )
    assert {service["id"] for service in response.context["results"].object_list} == {
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "dora-geispolsheim",
        "dora-distanciel-vannes",
        "autre-distanciel-geispolsheim",
        "autre-presentiel-nowhere",
        "autre-none-nowhere",
    }


def test_filter_reception_default(client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    reception_input = parse_response_to_soup(
        response, selector=f"input[value='{data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value}']"
    )
    assert "checked" in reception_input.attrs
    assert {service["id"] for service in response.context["results"].object_list} == {
        "dora-presentiel-vannes",
        "autre-presentiel-vannes",
        "dora-distanciel-vannes",
    }


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
            url, {"city": vannes.slug, "category": category, "reception": data_inclusion_v1.ModeAccueil.EN_PRESENTIEL}
        )
    )
    [radio_input] = simulated_page.find_all(
        "input",
        attrs={"type": "radio", "name": "reception", "value": data_inclusion_v1.ModeAccueil.A_DISTANCE},
    )
    radio_input["checked"] = ""
    [radio_input] = simulated_page.find_all(
        "input",
        attrs={"type": "radio", "name": "reception", "value": data_inclusion_v1.ModeAccueil.EN_PRESENTIEL},
    )
    del radio_input.attrs["checked"]
    update_page_with_htmx(
        simulated_page,
        f"form[hx-get='{url}']",
        htmx_client.get(
            url, {"city": vannes.slug, "category": category, "reception": data_inclusion_v1.ModeAccueil.A_DISTANCE}
        ),
    )

    response = client.get(
        url, {"city": vannes.slug, "category": category, "reception": data_inclusion_v1.ModeAccueil.A_DISTANCE}
    )
    fresh_page = parse_response_to_soup(response)

    assertSoupEqual(simulated_page, fresh_page)
