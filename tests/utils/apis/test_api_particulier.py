import datetime
import time

import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask

from itou.eligibility.tasks import certify_criteria
from itou.users.models import User
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    rsa_certified_mocker,
    rsa_not_certified_mocker,
    rsa_not_found_mocker,
)
from tests.asp.factories import CommuneFactory, CountryFranceFactory, CountryOutsideEuropeFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


RSA_ENDPOINT = f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active"


def test_build_params_from(snapshot, caplog):
    birth_place = CommuneFactory(code="07141")
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True, jobseeker_profile__birth_place=birth_place)
    job_seeker = User.objects.select_related(
        "jobseeker_profile", "jobseeker_profile__birth_place", "jobseeker_profile__birth_country"
    ).get(pk=job_seeker.pk)
    assert api_particulier._build_params_from(job_seeker) == snapshot(name="api_particulier_build_params")
    assert api_particulier.has_required_info(job_seeker) is True

    job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)
    assert api_particulier.has_required_info(job_seeker) is False

    # Born in France without a birth country.
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=CountryFranceFactory(),
    )
    assert api_particulier.has_required_info(job_seeker) is False

    # Job seeker born outside of France
    country = CountryOutsideEuropeFactory()
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=country,
    )
    params = api_particulier._build_params_from(job_seeker)
    assert api_particulier.has_required_info(job_seeker) is True
    assert "codeInseeLieuDeNaissance" not in params.keys()
    assert params["codePaysLieuDeNaissance"][2:] == country.code


def test_not_found(respx_mock):
    respx_mock.get(RSA_ENDPOINT).respond(404, json=rsa_not_found_mocker())
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == rsa_not_found_mocker()
    assert crit.certified is None
    assert crit.certification_period is None


@freeze_time(datetime.datetime(2024, 1, 1, 11, 11, 11, tzinfo=datetime.UTC))
@pytest.mark.parametrize(
    "has_retry_after,expected",
    [
        (True, {"delay": 1}),
        (False, {"eta": datetime.datetime(2024, 1, 1, 11, 11, 12, tzinfo=datetime.UTC)}),
    ],
)
def test_too_many_requests(expected, has_retry_after, respx_mock):
    delay_s = 1
    reset_ts = int(time.time() + delay_s)
    headers = {
        "ratelimit-limit": "20",
        "ratelimit-remaining": "0",
        "ratelimit-reset": f"{reset_ts}",
    }
    if has_retry_after:
        headers["retry-after"] = f"{delay_s}"
    respx_mock.get(RSA_ENDPOINT).respond(503, headers=headers, json={})
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    with pytest.raises(RetryTask) as exc_info:
        certify_criteria(diag)
    for attrname, value in expected.items():
        assert getattr(exc_info.value, attrname) == value


def test_service_unavailable(respx_mock, caplog):
    reason = "Erreur inconnue du fournisseur de données"
    response = {
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
    }
    respx_mock.get(RSA_ENDPOINT).respond(
        503,
        headers={
            "ratelimit-limit": "20",
            "ratelimit-remaining": "14",
            "ratelimit-reset": "1729587616",
        },
        json=response,
    )
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    with pytest.raises(RetryTask) as exc_info:
        certify_criteria(diag)
    assert exc_info.value.delay is None
    assert exc_info.value.eta == datetime.datetime(2024, 10, 22, 9, 0, 16, tzinfo=datetime.UTC)
    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text


def test_gateway_timeout(respx_mock, mocker, caplog):
    reason = "The read operation timed out"
    response = {"error": "null", "reason": reason, "message": "null"}
    respx_mock.get(RSA_ENDPOINT).respond(504, json=response)

    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    with pytest.raises(RetryTask) as exc_info:
        certify_criteria(diag)
    assert exc_info.value.delay == 600
    assert exc_info.value.eta is None
    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text


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
