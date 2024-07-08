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
    api_mock = respx_mock.get("https://fake.api.gouv.fr/search/services")
    api_mock.respond(
        200,
        json={
            "items": [
                {
                    "service": {
                        "id": "svc1",
                        "source": "dora",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["a-distance"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc1",
                    },
                    "distance": 1,
                },
                {
                    "service": {
                        "id": "svc2",
                        "source": "fake",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc2",
                    },
                    "distance": 3,
                },
                {
                    "service": {
                        "id": "svc3",
                        "source": "dora",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel", "a-distance"],
                    },
                    "distance": 2,
                },
                {
                    "service": {
                        "id": "svc4",
                        "source": "fake",
                        "thematiques": ["a--b"],
                        "modes_accueil": ["en-presentiel"],
                        "lien_source": "https://fake.api.gouv.fr/services/svc4",
                    },
                    "distance": 5,
                },
            ]
        },
    )

    assert views.get_data_inclusion_services(None) == []
    random.seed(0)  # ensure the mock data is stable
    mocked_final_response = [
        {
            "dora_service_redirect_url": "/company/dora-service-redirect/fake/svc4",
            "id": "svc4",
            "lien_source": "https://fake.api.gouv.fr/services/svc4",
            "modes_accueil": ["en-presentiel"],
            "source": "fake",
            "thematiques": ["a--b"],
            "thematiques_display": {"A"},
        },
        {
            "dora_service_redirect_url": "/company/dora-service-redirect/fake/svc2",
            "id": "svc2",
            "lien_source": "https://fake.api.gouv.fr/services/svc2",
            "modes_accueil": ["en-presentiel"],
            "source": "fake",
            "thematiques": ["a--b"],
            "thematiques_display": {"A"},
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
