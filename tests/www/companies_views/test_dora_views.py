import random

import freezegun
import httpcore
from django.urls import reverse

from itou.www.companies_views import views
from tests.utils.test import parse_response_to_soup


def test_displayable_thematique():
    assert views.displayable_thematique("une-thematique-comme-ça--et-une-sous-thematique") == "UNE THEMATIQUE COMME ÇA"


def test_get_data_inclusion_services(settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    API_TEST_SERVICES = [
        {
            "service": {
                "id": "svc1",
                "source": "dora",
                "thematiques": ["a--b"],
                "modes_accueil": ["en presentiel", "a-distance"],
                "lien_source": "https://fake.api.gouv.fr/services/svc1",
            },
            "distance": 1,
        },
        {
            "service": {
                "id": "svc2",
                "source": "fake",
                "thematiques": ["a--b", "c--d"],
                "modes_accueil": ["en-presentiel"],
                "lien_source": "https://fake.api.gouv.fr/services/svc2",
            },
            "distance": 3,
        },
        {
            "service": {
                "id": "svc3",
                "source": "truc",
                "thematiques": ["c--d", "f--b"],
                "modes_accueil": ["en-presentiel"],
            },
            "distance": 2,
        },
        {
            "service": {
                "id": "svc4",
                "source": "fake",
                "thematiques": ["d--e"],
                "modes_accueil": ["en-presentiel"],
                "lien_source": "https://fake.api.gouv.fr/services/svc4",
            },
            "distance": 5,
        },
        {
            "service": {
                "id": "svc5",
                "source": "soliguide",
                "thematiques": ["c--e"],
                "modes_accueil": ["en-presentiel"],
                "lien_source": "https://fake.api.gouv.fr/services/svc4",
            },
            "distance": 1,
        },
    ]
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    api_mock.respond(
        200,
        json={
            "items": API_TEST_SERVICES,
        },
    )

    assert views.get_data_inclusion_services(None) == []
    random.seed(0)  # ensure the mock data is stable
    mocked_final_response = [
        {
            "dora_service_redirect_url": "/company/dora-service-redirect/fake/svc4",
            "id": "svc4",
            "lien_source": "https://fake.api.gouv.fr/services/svc4",
            "modes_accueil": [
                "en-presentiel",
            ],
            "source": "fake",
            "thematiques": [
                "d--e",
            ],
            "thematiques_display": {
                "D",
            },
        },
        {
            "dora_service_redirect_url": "/company/dora-service-redirect/truc/svc3",
            "id": "svc3",
            "modes_accueil": [
                "en-presentiel",
            ],
            "source": "truc",
            "thematiques": [
                "c--d",
                "f--b",
            ],
            "thematiques_display": {
                "C",
                "F",
            },
        },
        {
            "dora_service_redirect_url": "/company/dora-service-redirect/fake/svc2",
            "id": "svc2",
            "lien_source": "https://fake.api.gouv.fr/services/svc2",
            "modes_accueil": [
                "en-presentiel",
            ],
            "source": "fake",
            "thematiques": [
                "a--b",
                "c--d",
            ],
            "thematiques_display": {
                "A",
                "C",
            },
        },
    ]
    with freezegun.freeze_time("2024-01-01") as frozen_datetime:
        # make the actual API request
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 1
        # hit the cache on the second call
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 1

        # expire the cache key
        frozen_datetime.move_to("2024-01-02")
        random.seed(0)  # ensure the mock data is stable
        assert views.get_data_inclusion_services("75056") == mocked_final_response
        assert api_mock.call_count == 2

    # Test with Soliguide experiment
    with freezegun.freeze_time("2025-01-01") as frozen_datetime:  # note the different date
        result = views.get_data_inclusion_services("59056")
        # we mandatorily have a soliguide service (test random.seed is fixed so we know where)
        assert result[1]["source"] == "soliguide"
        # all thematiques are different
        assert result[0]["thematiques_display"] == {"D"}
        assert result[1]["thematiques_display"] == {"C"}
        assert result[2]["thematiques_display"] == {"C", "A"}

    # Test with fewer values or no answer
    with freezegun.freeze_time("2025-02-01") as frozen_datetime:  # note the different date
        api_mock.respond(
            200,
            json={
                "items": API_TEST_SERVICES[:1],
            },
        )
        assert views.get_data_inclusion_services("59056") == []

    with freezegun.freeze_time("2025-02-02") as frozen_datetime:  # note the different date
        api_mock.respond(
            200,
            json={
                "items": API_TEST_SERVICES[:2],
            },
        )
        assert views.get_data_inclusion_services("59056") == [
            {
                "dora_service_redirect_url": "/company/dora-service-redirect/fake/svc2",
                "id": "svc2",
                "lien_source": "https://fake.api.gouv.fr/services/svc2",
                "modes_accueil": [
                    "en-presentiel",
                ],
                "source": "fake",
                "thematiques": [
                    "a--b",
                    "c--d",
                ],
                "thematiques_display": {
                    "A",
                    "C",
                },
            },
        ]

    with freezegun.freeze_time("2025-02-03") as frozen_datetime:  # note the different date
        api_mock.respond(
            200,
            json={
                "items": API_TEST_SERVICES[:3],
            },
        )
        result = views.get_data_inclusion_services("59056")
        assert result[0]["thematiques_display"] == {"C", "F"}
        assert result[1]["thematiques_display"] == {"C", "A"}

    with freezegun.freeze_time("2024-01-01") as frozen_datetime:
        api_mock.mock(side_effect=httpcore.TimeoutException)
        assert views.get_data_inclusion_services("89000") == []


def test_hx_dora_services(htmx_client, snapshot, settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    base_service = {
        "id": "svc1",
        "source": "dora",
        "nom": "Coupe les cheveux",
        "thematiques": ["a--b"],
        "modes_accueil": ["en-presentiel"],
        "lien_source": "https://fake.api.gouv.fr/services/svc1",
        "structure": {"nom": "Coiffeur"},
    }
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": base_service,
                    "distance": 1,
                },
            ]
        },
    )
    response = htmx_client.get(reverse("companies_views:hx_dora_services", kwargs={"code_insee": "75056"}))
    dora_service_card = parse_response_to_soup(response, selector=".card-body")
    assert str(dora_service_card) == snapshot(name="Dora service card")


def test_hx_dora_services_with_address(htmx_client, snapshot, settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    base_service = {
        "id": "svc1",
        "source": "dora",
        "nom": "Coupe les cheveux",
        "thematiques": ["a--b"],
        "modes_accueil": ["en-presentiel"],
        "lien_source": "https://fake.api.gouv.fr/services/svc1",
        "structure": {"nom": "Coiffeur"},
        "code_postal": "75056",
        "commune": "Paris",
    }
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": base_service,
                    "distance": 1,
                },
            ]
        },
    )

    response = htmx_client.get(reverse("companies_views:hx_dora_services", kwargs={"code_insee": "75056"}))
    dora_service_card = parse_response_to_soup(response, selector=".card-body")
    assert str(dora_service_card) == snapshot(name="Dora service card with address")


def test_dora_service_redirect(client, settings, respx_mock):
    settings.API_DATA_INCLUSION_BASE_URL = "https://fake.api.gouv.fr/"
    settings.API_DATA_INCLUSION_TOKEN = "fake-token"
    url = reverse("companies_views:dora_service_redirect", kwargs={"source": "dora", "service_id": "foo"})

    respx_mock.get("https://fake.api.gouv.fr/services/dora/foo").respond(200, json={"id": "foo", "source": "dora"})
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == (
        "https://dora.inclusion.beta.gouv.fr/services/di--dora--foo"
        "?mtm_campaign=LesEmplois&mtm_kwd=GeneriqueDecouvrirService"
    )

    respx_mock.get("https://fake.api.gouv.fr/services/dora/foo").respond(500)
    response = client.get(url)
    assert response.status_code == 404
