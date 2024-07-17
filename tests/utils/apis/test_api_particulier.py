import datetime

import pytest
from django.conf import settings

from itou.users.models import User
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    rsa_certified_mocker,
    rsa_not_certified_mocker,
    rsa_not_found_mocker,
)
from tests.asp.factories import CommuneFactory, CountryFranceFactory, CountryOutsideEuropeFactory
from tests.users.factories import JobSeekerFactory


RSA_ENDPOINT = f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active"


def test_build_params_from(snapshot, caplog):
    birth_place = CommuneFactory(code="07141")
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True, jobseeker_profile__birth_place=birth_place)
    job_seeker = User.objects.select_related(
        "jobseeker_profile", "jobseeker_profile__birth_place", "jobseeker_profile__birth_country"
    ).get(pk=job_seeker.pk)
    assert api_particulier._build_params_from(job_seeker) == snapshot(name="api_particulier_build_params")

    api_particulier._build_params_from(job_seeker)
    # Missing parameters.
    job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)
    with pytest.raises(KeyError):
        api_particulier._build_params_from(job_seeker)
        assert "Missing information" in caplog.text

    # Born in France without a birth country.
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=CountryFranceFactory(),
    )
    with pytest.raises(KeyError):
        api_particulier._build_params_from(job_seeker)
        assert "Missing information" in caplog.text

    # Job seeker born outside of France
    country = CountryOutsideEuropeFactory()
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=country,
    )
    params = api_particulier._build_params_from(job_seeker)
    assert "codeInseeLieuDeNaissance" not in params.keys()
    assert params["codePaysLieuDeNaissance"][2:] == country.code


def test_certify_brsa__missing_information(respx_mock, caplog):
    # Mocking the request is useless as no request should be done at all.
    # Plus, respx will raise an error when trying to make an unmocked request.
    job_seeker = JobSeekerFactory()
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
    assert response["raw_response"] is None
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_not_found(respx_mock):
    json = rsa_not_found_mocker()
    respx_mock.get(RSA_ENDPOINT).respond(404, json=json)
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_service_unavailable(settings, respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep")
    reason = "Erreur inconnue du fournisseur de données"
    json = {
        "errors": [
            {
                "code": "37999",
                "title": reason,
                "detail": "La réponse retournée par le fournisseur de données est invalide et inconnue de "
                "notre service. L'équipe technique a été notifiée de cette erreur pour investigation.",
                "source": None,
                "meta": {"provider": "CNAV"},
            }
        ]
    }
    respx_mock.get(RSA_ENDPOINT).respond(
        503,
        json=json,
    )
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_provider_unknown(settings, respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep")
    reason = (
        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service. L'équipe "
        "technique a été notifiée de cette erreur pour investigation."
    )
    json = {
        "error": "provider_unknown_error",
        "reason": reason,
        "message": reason,
    }
    respx_mock.get(RSA_ENDPOINT).respond(
        503,
        json=json,
    )
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_bad_params(settings, respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep")
    reason = "Entité non traitable"
    json = {
        "errors": [
            {
                "code": "00364",
                "title": reason,
                "detail": "Le sexe n'est pas correctement formaté (m ou f)",
                "source": None,
                "meta": {},
            }
        ]
    }
    respx_mock.get(RSA_ENDPOINT).respond(
        400,
        json=json,
    )
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_forbidden(settings, respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep")
    reason = "Accès non autorisé"
    json = {
        "errors": [
            {
                "code": "50002",
                "title": reason,
                "detail": "Le jeton d'accès n'a pas été trouvé ou est expiré.",
                "source": None,
                "meta": {},
            }
        ]
    }
    respx_mock.get(RSA_ENDPOINT).respond(
        401,
        json=json,
    )
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_gateway_timeout(respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep", mocker.MagicMock())
    reason = "The read operation timed out"
    json = {"error": None, "reason": reason, "message": "null"}
    respx_mock.get(RSA_ENDPOINT).respond(504, json=json)

    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


def test_too_many_requests(respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep", mocker.MagicMock())
    reason = "Vous avez effectué trop de requêtes"
    json = {"errors": ["Vous avez effectué trop de requêtes"]}
    respx_mock.get(RSA_ENDPOINT).respond(429, json=json)

    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == json
    assert response["is_certified"] is None
    assert response["start_at"] is None
    assert response["end_at"] is None


# BRSA
def test_certify_brsa(respx_mock):
    # Certified
    respx_mock.get(RSA_ENDPOINT).respond(
        200,
        json=rsa_certified_mocker(),
    )

    birth_place = CommuneFactory(code="07141")
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True, jobseeker_profile__birth_place=birth_place)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
        assert response["raw_response"] == rsa_certified_mocker()
        assert response["is_certified"] is True
        assert response["start_at"] == datetime.date(2024, 8, 1)
        assert response["end_at"] == datetime.date(2024, 10, 31)

        # Not certified
        respx_mock.get(RSA_ENDPOINT).respond(
            200,
            json=rsa_not_certified_mocker(),
        )
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
        assert response["raw_response"] == rsa_not_certified_mocker()
        assert response["is_certified"] is False
        assert response["start_at"] is None
        assert response["end_at"] is None
