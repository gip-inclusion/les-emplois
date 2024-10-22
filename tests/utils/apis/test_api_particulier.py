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
    assert "Missing parameters" in response["raw_response"]
    assert response["is_certified"] == ""
    assert response["start_at"] == ""
    assert response["end_at"] == ""


def test_not_found(respx_mock):
    respx_mock.get(RSA_ENDPOINT).respond(404, json=rsa_not_found_mocker())
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
    assert response["raw_response"] == rsa_not_found_mocker()
    assert response["is_certified"] == ""
    assert response["start_at"] == ""
    assert response["end_at"] == ""


def test_service_unavailable(settings, respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep")
    reason = "Erreur inconnue du fournisseur de données"
    respx_mock.get(RSA_ENDPOINT).respond(
        503,
        json={
            "errors": [
                {
                    "code": "37999",
                    "title": reason,
                    "detail": "La réponse retournée par le fournisseur de données est invalide et inconnue de notre"
                    "service. L'équipe technique a été notifiée de cette erreur pour investigation.",
                    "source": "null",
                    "meta": {"provider": "CNAV"},
                }
            ]
        },
    )
    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == reason
    assert response["is_certified"] == ""
    assert response["start_at"] == ""
    assert response["end_at"] == ""


def test_gateway_timeout(respx_mock, mocker, caplog):
    mocker.patch("tenacity.nap.time.sleep", mocker.MagicMock())
    reason = "The read operation timed out"
    respx_mock.get(RSA_ENDPOINT).respond(504, json={"error": "null", "reason": reason, "message": "null"})

    job_seeker = JobSeekerFactory(born_in_france=True)
    with api_particulier.client() as client:
        response = api_particulier.revenu_solidarite_active(client, job_seeker)

    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
    assert response["raw_response"] == reason
    assert response["is_certified"] == ""
    assert response["start_at"] == ""
    assert response["end_at"] == ""


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
        assert response["is_certified"]
        assert response["start_at"] == datetime.datetime(2024, 8, 1)
        assert response["end_at"] == datetime.datetime(2024, 10, 31)

        # Not certified
        respx_mock.get(RSA_ENDPOINT).respond(
            200,
            json=rsa_not_certified_mocker(),
        )
        response = api_particulier.revenu_solidarite_active(client, job_seeker)
        assert response["raw_response"] == rsa_not_certified_mocker()
        assert not response["is_certified"]
        assert response["start_at"] == ""
        assert response["end_at"] == ""
