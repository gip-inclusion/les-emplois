import datetime

import httpx
import pytest
import tenacity
from django.db.models import F

from itou.users.models import User
from itou.utils.apis.api_particulier import APIParticulierClient
from tests.asp.factories import CommuneFactory
from tests.users.factories import JobSeekerFactory


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


# TODO: update that.
def get_job_seeker_qs():
    birth_place = CommuneFactory(code="07141")
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True, jobseeker_profile__birth_place=birth_place)
    return (
        User.objects.values(
            "first_name",
            "last_name",
            "birthdate",
            "title",
        )
        .annotate(birth_country_code=F("jobseeker_profile__birth_country__code"))
        .annotate(birth_place_code=F("jobseeker_profile__birth_place__code"))
        .get(pk=job_seeker.pk)
    )


def test_build_params_from(snapshot):
    assert APIParticulierClient._build_params_from(get_job_seeker_qs()) == snapshot(
        name="api_particulier_build_params"
    )


# BRSA
def test_certify_brsa(settings, respx_mock):
    settings.API_PARTICULIER_BASE_URL = "https://fake-api-particulier.com/api/"
    mocked_data = {"status": "beneficiaire", "majoration": "true", "dateDebut": "1992-11-20", "dateFin": "1993-02-20"}
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        200,
        json=mocked_data,
    )

    client = APIParticulierClient(job_seeker=get_job_seeker_qs())
    received_data, is_certified, certification_period = client.revenu_solidarite_active()
    assert received_data == mocked_data
    assert is_certified
    assert certification_period == (datetime.datetime(1992, 11, 20), datetime.datetime(1993, 2, 20))

    mocked_data = {"status": "non_beneficiaire", "majoration": "null", "dateDebut": "null", "dateFin": "null"}
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        200,
        json=mocked_data,
    )
    received_data, is_certified, certification_period = client.revenu_solidarite_active()
    assert received_data == mocked_data
    assert not is_certified
    assert certification_period == ""
