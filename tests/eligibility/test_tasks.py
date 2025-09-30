import copy
import datetime

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.eligibility.tasks import async_certify_criteria_by_api_particulier, certify_criteria_by_api_particulier
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import JobSeekerProfile
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    RESPONSES,
    ResponseKind,
)
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


def fake_response_code(response):
    response = copy.deepcopy(response)
    response["errors"][0]["code"] = "12345"
    return response


def fake_multiple_errors(response):
    response = copy.deepcopy(response)
    response["errors"].append(response["errors"][0])
    return response


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
@pytest.mark.usefixtures("api_particulier_settings")
class TestCertifyCriteriaApiParticulier:
    @pytest.mark.parametrize("criteria_kind", CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS)
    @freeze_time("2025-01-06")
    def test_queue_task(self, criteria_kind, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[criteria_kind])
        respx_mock.get(settings.API_PARTICULIER_BASE_URL + api_particulier.ENDPOINTS[criteria_kind]).respond(
            json=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]
        )

        async_certify_criteria_by_api_particulier.call_local(
            eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
        )

        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=criteria_kind,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is True
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]
        assert criterion.certification_period == InclusiveDateRange(
            datetime.date(2024, 8, 1), datetime.date(2025, 4, 8)
        )
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(
            jobseeker_profile.identity_certifications.all(),
            [IdentityCertificationAuthorities.API_PARTICULIER],
            transform=lambda certification: certification.certifier,
        )

    # The API returns the same error messages for each endpoint called by us.
    # It would be useless to test them all.
    def test_retry_task_rate_limits(self, factory, respx_mock):
        with freeze_time("2024-09-12T00:00:00Z"):
            eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
            respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            )

            with pytest.raises(RetryTask) as exc_info:
                async_certify_criteria_by_api_particulier.call_local(
                    eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
                )

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
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    @pytest.mark.parametrize(
        "status_code,json_data,headers,retry_task_exception",
        [
            (400, {}, None, False),
            # "errors" is not in data, something went wrong, let the exception
            # bubble up for a retry.
            (404, {}, None, False),
            (429, {}, None, False),
            (429, {}, {"Retry-After": "123"}, True),
            (502, {}, None, False),
        ],
    )
    def test_retry_task_on_http_error_status_codes(
        self, status_code, json_data, headers, retry_task_exception, factory, respx_mock
    ):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code, json=json_data, headers=headers
        )
        try:
            certify_criteria_by_api_particulier(eligibility_diagnosis)
        except RetryTask:
            retry_task = True
        except Exception:
            retry_task = False
        else:
            retry_task = None
        assert retry_task == retry_task_exception
        # Huey catches the exception and retries the task.
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)

        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_ignores_api_particulier_internal_error(self, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        response = RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.PROVIDER_UNKNOWN_ERROR]
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code=502, json=response
        )
        # Does not raise a RetryTask, this specific error is ignored.
        async_certify_criteria_by_api_particulier.call_local(
            eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
        )
        assert len(respx_mock.calls) == 1
        criterion = eligibility_diagnosis.selected_administrative_criteria.get(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
        )
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api == response
        assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    @pytest.mark.parametrize("mutate_response", [fake_response_code, fake_multiple_errors])
    def test_raises_on_api_particulier_internal_error_with_unknown_error_code(
        self, factory, mutate_response, respx_mock
    ):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        response = mutate_response(RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.PROVIDER_UNKNOWN_ERROR])
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code=502, json=response
        )
        with pytest.raises(httpx.HTTPStatusError):
            async_certify_criteria_by_api_particulier.call_local(
                eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
            )
        assert len(respx_mock.calls) == 1
        criterion = eligibility_diagnosis.selected_administrative_criteria.get(
            administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
        )
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_no_retries_when_diag_does_not_exist(self, caplog, factory):
        eligibility_diagnosis_model = factory._meta.model
        modelname = eligibility_diagnosis_model._meta.model_name
        async_certify_criteria_by_api_particulier.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]
