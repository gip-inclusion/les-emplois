import httpx
import pytest
import tenacity

from itou.utils.apis.api_particulier import APIParticulierClient


def test_token_scope(settings, respx_mock):
    # Returns valid scopes for our token.
    settings.API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}introspect").respond(
        200,
        json={
            "_id": "something-random",
            "name": "",
            "scopes": [
                "revenu_solidarite_active",
                "revenu_solidarite_active_majoration",
                "allocation_adulte_handicape",
                "allocation_soutien_familial",
            ],
        },
    )
    client = APIParticulierClient()
    assert client.test_scope_validity()


def test_service_unavailable(settings, respx_mock, mocker, caplog):
    settings.API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
    # TODO: change to RSA endpoint.
    url = f"{settings.API_PARTICULIER_BASE_URL}introspect"
    mocker.patch("tenacity.nap.time.sleep", mocker.MagicMock())
    respx_mock.get(url).respond(
        503,
        json={
            "errors": [
                {
                    "code": "37999",
                    "title": "Erreur inconnue du fournisseur de données",
                    "detail": "La réponse retournée par le fournisseur de données est invalide et inconnue de notre"
                    "service. L'équipe technique a été notifiée de cette erreur pour investigation.",
                    "source": "null",
                    "meta": {"provider": "CNAV"},
                }
            ]
        },
    )
    client = APIParticulierClient()
    with pytest.raises(tenacity.RetryError):
        client.test_scope_validity()
    assert url in caplog.text


def test_not_found(settings, respx_mock):
    settings.API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
    # TODO: change to RSA endpoint.
    # TODO: don't raise but do something. What?
    url = f"{settings.API_PARTICULIER_BASE_URL}introspect"
    respx_mock.get(url).respond(404, json={"error": "null", "reason": "null", "message": "null"})
    client = APIParticulierClient()
    with pytest.raises(httpx.HTTPStatusError):
        client.test_scope_validity()


def test_gateway_timeout(settings, respx_mock, mocker, caplog):
    settings.API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
    # TODO: change to RSA endpoint.
    url = f"{settings.API_PARTICULIER_BASE_URL}introspect"
    mocker.patch("tenacity.nap.time.sleep", mocker.MagicMock())
    reason = "The read operation timed out"
    respx_mock.get(url).respond(
        504,
        json={"error": "null", "reason": reason, "message": "null"},
    )
    client = APIParticulierClient()
    with pytest.raises(tenacity.RetryError):
        client.test_scope_validity()
    assert url in caplog.text
    assert reason in caplog.text


# BRSA
