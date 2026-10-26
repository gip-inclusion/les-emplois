import datetime
import hashlib

import httpx
import pytest
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured

from itou.utils.apis import rdv_insertion
from itou.utils.mocks.rdv_insertion import RDV_INSERTION_USER_SEARCH_BODY
from tests.users.factories import JobSeekerFactory


SEARCH_URL = "https://rdv-insertion.fake/api/plateforme_inclusion/users/search"
NIR = "285032612345653"


@pytest.fixture(autouse=True)
def rdvi_settings(settings):
    settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_BASE_URL = "https://rdv-insertion.fake/api/plateforme_inclusion/"
    settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN = "S3cr3t!"
    return settings


def test_improperly_configured(rdvi_settings):
    rdvi_settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN = ""
    with pytest.raises(ImproperlyConfigured):
        rdv_insertion.get_client()


def test_search_user_by_nir(respx_mock):
    respx_mock.post(SEARCH_URL, json={"nir": NIR}, headers={"Authorization": "Bearer S3cr3t!"}).respond(
        200, json={"user": {"id": 1, "follow_ups": []}}
    )
    assert rdv_insertion.get_client().search_user_by_nir(NIR) == {"id": 1, "follow_ups": []}


@pytest.mark.parametrize(
    "status_code, error",
    [
        (404, "Aucun usager ne correspond à ce NIR"),
        (409, "Plusieurs usagers correspondent à ce NIR"),
    ],
)
def test_search_user_by_nir_not_found_or_several(respx_mock, status_code, error):
    respx_mock.post(SEARCH_URL).respond(status_code, json={"errors": [error]})
    assert rdv_insertion.get_client().search_user_by_nir(NIR) is None


def test_search_user_by_nir_errors(respx_mock):
    client = rdv_insertion.get_client()

    respx_mock.post(SEARCH_URL).mock(side_effect=httpx.ReadTimeout)
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="ReadTimeout"):
        client.search_user_by_nir(NIR)

    respx_mock.post(SEARCH_URL).respond(500)
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="HTTPStatusError"):
        client.search_user_by_nir(NIR)

    respx_mock.post(SEARCH_URL).respond(200, content="not json")
    with pytest.raises(rdv_insertion.RdvInsertionApiError, match="JSONDecodeError"):
        client.search_user_by_nir(NIR)


@pytest.mark.parametrize(
    "status_code, body, expected_follow_ups, expected_ttl",
    [
        (
            200,
            RDV_INSERTION_USER_SEARCH_BODY,
            RDV_INSERTION_USER_SEARCH_BODY["user"]["follow_ups"],
            datetime.timedelta(hours=1),
        ),
        (404, {"errors": ["Aucun usager ne correspond à ce NIR"]}, [], datetime.timedelta(days=1)),
    ],
)
def test_get_follow_ups_is_cached(respx_mock, status_code, body, expected_follow_ups, expected_ttl):
    job_seeker = JobSeekerFactory(jobseeker_profile__nir=NIR)
    route = respx_mock.post(SEARCH_URL).respond(status_code, json=body)

    assert rdv_insertion.get_follow_ups(job_seeker) == expected_follow_ups
    assert route.call_count == 1
    cache_ttl = caches["failsafe"].ttl(f"rdv-insertion-follow-ups:{hashlib.sha256(NIR.encode()).hexdigest()}")
    assert cache_ttl == pytest.approx(expected_ttl.total_seconds(), abs=1)

    # Subsequent calls should hit the cache
    assert rdv_insertion.get_follow_ups(job_seeker) == expected_follow_ups
    assert route.call_count == 1


def test_get_follow_ups_without_nir(respx_mock):
    # No route: any request to rdv-insertion would fail the test
    assert rdv_insertion.get_follow_ups(JobSeekerFactory(jobseeker_profile__nir="")) == []


def test_get_follow_ups_when_rdv_insertion_is_unavailable(respx_mock, caplog):
    route = respx_mock.post(SEARCH_URL).respond(500)
    job_seeker = JobSeekerFactory(jobseeker_profile__nir=NIR)

    assert rdv_insertion.get_follow_ups(job_seeker) == []
    assert "rdv-insertion is unavailable: Error requesting rdv-insertion API: HTTPStatusError" in caplog.messages

    # rdv-insertion is not called again for this job seeker for a minute
    assert rdv_insertion.get_follow_ups(job_seeker) == []
    assert route.call_count == 1
    cache_ttl = caches["failsafe"].ttl(f"rdv-insertion-follow-ups:{hashlib.sha256(NIR.encode()).hexdigest()}")
    assert cache_ttl == pytest.approx(datetime.timedelta(minutes=1).total_seconds(), abs=1)

    # But it still is for another job seeker
    assert rdv_insertion.get_follow_ups(JobSeekerFactory()) == []
    assert route.call_count == 2


def test_get_follow_ups_after_nir_correction(respx_mock):
    route = respx_mock.post(SEARCH_URL).respond(200, json=RDV_INSERTION_USER_SEARCH_BODY)
    job_seeker = JobSeekerFactory(jobseeker_profile__nir=NIR)
    assert rdv_insertion.get_follow_ups(job_seeker) == RDV_INSERTION_USER_SEARCH_BODY["user"]["follow_ups"]

    job_seeker.jobseeker_profile.nir = "185032612345681"
    route.respond(404, json={"errors": ["Aucun usager ne correspond à ce NIR"]})
    # The follow-ups of the former NIR are not shown anymore
    assert rdv_insertion.get_follow_ups(job_seeker) == []
    assert route.call_count == 2


def test_get_follow_ups_without_configuration(respx_mock, rdvi_settings):
    # No route: any request to rdv-insertion would fail the test
    rdvi_settings.RDV_INSERTION_PLATEFORME_INCLUSION_API_TOKEN = None

    assert rdv_insertion.get_follow_ups(JobSeekerFactory(jobseeker_profile__nir=NIR)) == []
