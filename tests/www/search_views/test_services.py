import random
from functools import partial
from urllib.parse import urlsplit

import pytest
from data_inclusion.schema import v1 as data_inclusion_v1
from django.http import QueryDict
from django.urls import reverse
from itoutils.django.nexus.token import decode_token
from jwcrypto import jwt
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiException
from tests.cities.factories import create_city_vannes
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, parse_response_to_soup, pretty_indented


first_service_hyperlink_selector = "#services-search-results > .c-box--results:first-child a"


@pytest.fixture(name="search_services_route")
def search_services_route_fixture(respx_mock, settings):
    return respx_mock.route(url=f"{global_constants.API_DATA_INCLUSION_BASE_URL}/api/v1/search/services").respond(
        json={
            "items": [
                {
                    "service": {
                        "id": "svc1",
                        "source": "dora",
                        "nom": "Coupe les cheveux",
                        "modes_accueil": [data_inclusion_v1.ModeAccueil.A_DISTANCE],
                        "lien_source": f"{settings.DORA_BASE_URL}/services/svc1",
                        "structure": {"nom": "Coiffeur"},
                        "code_postal": "56260",
                        "description": "Coupe les cheveux longs",
                    },
                },
                {
                    "service": {
                        "id": "svc2",
                        "source": "dora",
                        "nom": "Coupe également les cheveux",
                        "modes_accueil": [data_inclusion_v1.ModeAccueil.EN_PRESENTIEL],
                        "lien_source": f"{settings.DORA_BASE_URL}/services/svc2",
                        "structure": {"nom": "Coiffeur"},
                        "code_postal": "56260",
                        "description": "Coupe également les cheveux longs",
                    },
                },
                {
                    "service": {
                        "id": "svc3",
                        "source": "autre",
                        "nom": "Coupe aussi les cheveux",
                        "modes_accueil": list(data_inclusion_v1.ModeAccueil),
                        "structure": {"nom": "Coiffeur"},
                        "code_postal": "56260",
                        "description": "Coupe aussi les cheveux longs",
                    },
                },
                {
                    "service": {
                        "id": "svc4",
                        "source": "autre",
                        "nom": "Coupe entre autres les cheveux",
                        "modes_accueil": None,
                        "structure": {"nom": "Coiffeur"},
                        "code_postal": "56260",
                        "description": "Coupe entre autres les cheveux longs",
                    },
                },
            ]
        },
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
    expected_items = 4
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
        pytest.param(
            partial(PrescriberFactory, membership=True, membership__organization__authorized=True),
            id="prescriber_authorized",
        ),
        pytest.param(
            partial(PrescriberFactory, membership=True, membership__organization__authorized=False),
            id="prescriber_not_authorized",
        ),
        pytest.param(partial(LaborInspectorFactory, membership=True), id="labor_inspector"),
        pytest.param(ItouStaffFactory, id="itou_staff"),
    ],
)
def test_results_html_link(snapshot, client, mocker, search_services_route, user_factory):
    mocker.patch("itou.www.search_views.views.generate_token", autospec=dict, return_value="op_jwt_token")
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    if user_factory:
        client.force_login(user_factory())
    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert pretty_indented(parse_response_to_soup(response, selector=first_service_hyperlink_selector)) == snapshot()


def test_results_ordering(client, search_services_route):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))

    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": category})
    assert [service["id"] for service in response.context["results"].object_list] == ["svc2", "svc3", "svc1", "svc4"]


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


@pytest.mark.usefixtures("search_services_route")
@pytest.mark.parametrize(
    "JobSeekerFactory",
    (
        None,
        pytest.param(lambda: JobSeekerFactory(for_snapshot=True), id="with_job_seeker"),
    ),
)
def test_results_with_orientation_jwt(client, JobSeekerFactory):
    city = create_city_vannes()
    category = random.choice(list(data_inclusion_v1.Categorie))
    job_seeker = None
    if JobSeekerFactory:
        job_seeker = JobSeekerFactory()

    organization = PrescriberOrganizationFactory(authorized=True)
    prescriber = PrescriberFactory(membership=True, membership__organization=organization)
    client.force_login(prescriber)

    query = {"city": city.slug, "category": category}
    if job_seeker:
        query["job_seeker_public_id"] = job_seeker.public_id
    response = client.get(reverse("search:services_results"), query)

    result_a_tag = parse_response_to_soup(response, selector=first_service_hyperlink_selector)
    href_url = urlsplit(result_a_tag["href"])
    assert href_url.path == reverse("nexus:auto_login")

    href_query = QueryDict(href_url.query)
    next_url = urlsplit(href_query["next_url"])
    next_url_query = QueryDict(next_url.query)
    op = next_url_query["op"]
    with pytest.raises(KeyError):
        jwt.JWT(jwt=op).claims
    expected = {
        "prescriber": {
            "email": prescriber.email,
            "organization": {
                "siret": organization.siret,
                "uid": str(organization.uid),
            },
        },
    }
    if job_seeker:
        expected["beneficiary"] = {
            "uid": str(job_seeker.public_id),
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "email": job_seeker.email,
            "phone": job_seeker.phone,
            "france_travail_id": job_seeker.jobseeker_profile.pole_emploi_id,
        }
    assert decode_token(op) == expected


def test_category_error_suppression(client, search_services_route, snapshot):
    city = create_city_vannes()
    error_markup = """\
        <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
            <p><strong>Votre formulaire contient une erreur</strong></p>
            <ul class="mb-0">
                <li>Sélectionnez un choix valide. invalid n’en fait pas partie.</li>
            </ul>
        </div>"""

    response = client.get(reverse("search:services_results"), {"city": city.slug})
    assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot(
        name="suppressed_error"
    )
    assertNotContains(response, error_markup, html=True)

    response = client.get(reverse("search:services_results"), {"city": city.slug, "category": "invalid"})
    assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot(
        name="other_error_not_suppressed"
    )
    assertContains(response, error_markup, html=True, count=1)


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
