import datetime
from json import JSONDecodeError

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import async_certify_criteria
from itou.utils.mocks.api_particulier import rsa_certified_mocker
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
class TestCertifyCriteria:
    @freeze_time("2025-01-06")
    def test_queue_task(self, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
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
            datetime.date(2024, 8, 1), datetime.date(2025, 4, 8)
        )

    def test_retry_task_rate_limits(self, factory, respx_mock):
        with freeze_time("2024-09-12T00:00:00Z"):
            eligibility_diagnosis = factory(criteria_kinds=[AdministrativeCriteriaKind.RSA], certifiable=True)
            respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            )

            with pytest.raises(RetryTask) as exc_info:
                async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

            assert exc_info.value.delay == 1
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
        "data,exception",
        [
            ({"text": "Internal server error"}, JSONDecodeError),
            ({"json": {"error": "Internal server error"}}, httpx.HTTPError),
        ],
    )
    def test_retry_task_on_http_error(self, data, exception, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(500, **data)
        with pytest.raises(exception):
            async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        # Huey catches the exception and retries the task.

    def test_no_retry_on_exception(self, caplog, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
            side_effect=TypeError("Programming error")
        )
        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        assert "TypeError: Programming error" in caplog.text
