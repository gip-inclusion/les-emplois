import datetime

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import async_certify_criteria
from itou.utils.mocks.api_particulier import rsa_certified_mocker, rsa_maybe_CNAV_error
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


def create(factory, **kwargs):
    job_seeker = JobSeekerFactory(with_address=True, born_in_france=True)
    return factory(with_certifiable_criteria=True, job_seeker=job_seeker, **kwargs)


def iae_eligibility_factory():
    return create(IAEEligibilityDiagnosisFactory, from_employer=True)


def geiq_eligibility_factory():
    return create(GEIQEligibilityDiagnosisFactory, from_geiq=True)


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(iae_eligibility_factory, id="iae"),
        pytest.param(geiq_eligibility_factory, id="geiq"),
    ],
)
class TestCertifyCriteria:
    def test_queue_task(self, factory, respx_mock):
        eligibility_diagnosis = factory()
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
            json=rsa_certified_mocker()
        )

        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is True
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == rsa_certified_mocker()
        assert criterion.certification_period == InclusiveDateRange(
            datetime.date(2024, 8, 1), datetime.date(2024, 10, 31)
        )

    @pytest.mark.parametrize(
        "response,expected",
        [
            pytest.param(
                httpx.Response(429, headers={"Retry-After": "1"}, json={}),
                {"delay": 1},
                id="429-retry-after",
            ),
            pytest.param(
                # Observed on the API when making a large amount of requests quickly.
                httpx.Response(
                    503,
                    # datetime.datetime(2024, 9, 12, 0, 0, 1, tzinfo=datetime.UTC).timestamp() == 1726099201.0
                    headers={"RateLimit-Reset": "1726099201"},
                    json=rsa_maybe_CNAV_error(),
                ),
                {"eta": datetime.datetime(2024, 9, 12, 0, 0, 1, tzinfo=datetime.UTC)},
                id="503-ratelimit-reset",
            ),
        ],
    )
    def test_retry_task_rate_limits(self, expected, factory, response, respx_mock):
        with freeze_time("2024-09-12T00:00:00Z"):
            eligibility_diagnosis = factory()
            respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
                return_value=response
            )

            with pytest.raises(RetryTask) as exc_info:
                async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

            for attrname, value in expected.items():
                assert getattr(exc_info.value, attrname) == value
            assert len(respx_mock.calls) == 1
            SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
            criterion = SelectedAdministrativeCriteria.objects.filter(
                administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
                eligibility_diagnosis=eligibility_diagnosis,
            ).get()
            assert criterion.certified is None
            assert criterion.certified_at is None
            assert criterion.data_returned_by_api is None
            assert criterion.certification_period is None

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500, text="<h1>Internal server error</h1>"),
            httpx.Response(500, json={"error": "Internal server error"}),
        ],
    )
    def test_retry_task_error(self, factory, response, respx_mock):
        eligibility_diagnosis = factory()
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(return_value=response)

        with pytest.raises(RetryTask) as exc_info:
            async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

        assert exc_info.value.delay == 600
        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None

    def test_max_retries(self, caplog, factory, respx_mock):
        eligibility_diagnosis = factory()
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
            429, headers={"Retry-After": "1"}, json={}
        )

        class FakeTask:
            # Huey maintains this across retries.
            retries = 100

        # Does not raise a RetryTask.
        async_certify_criteria.call_local(
            eligibility_diagnosis._meta.model_name,
            eligibility_diagnosis.pk,
            task=FakeTask(),
        )
        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        assert (
            f"Retry limit reached for ‘{eligibility_diagnosis._meta.model_name}’ "
            f"PK ‘{eligibility_diagnosis.pk}’, bailing out."
        ) in caplog.text

    def test_connection_error(self, factory, respx_mock):
        eligibility_diagnosis = factory()
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
            side_effect=httpx.RequestError("Network issue")
        )

        with pytest.raises(RetryTask) as exc_info:
            async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

        assert exc_info.value.delay == 10
        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
