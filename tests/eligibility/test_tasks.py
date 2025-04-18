import datetime
from json import JSONDecodeError

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import async_certify_criteria
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import JobSeekerProfile
from itou.utils.mocks.api_particulier import aah_certified_mocker, asf_certified_mocker, rsa_certified_mocker
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
    @pytest.mark.parametrize(
        "endpoint,CRITERIA_KIND,api_returned_payload",
        [
            pytest.param(
                f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active",
                AdministrativeCriteriaKind.RSA,
                rsa_certified_mocker(),
                id="rsa",
            ),
            pytest.param(
                f"{settings.API_PARTICULIER_BASE_URL}v2/allocation-adulte-handicape",
                AdministrativeCriteriaKind.AAH,
                aah_certified_mocker(),
                id="aah",
            ),
            pytest.param(
                f"{settings.API_PARTICULIER_BASE_URL}v2/allocation-soutien-familial",
                AdministrativeCriteriaKind.PI,
                asf_certified_mocker(),
                id="pi",
            ),
        ],
    )
    @freeze_time("2025-01-06")
    def test_queue_task(self, endpoint, CRITERIA_KIND, api_returned_payload, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[CRITERIA_KIND])
        respx_mock.get(endpoint).respond(json=api_returned_payload)

        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

        assert len(respx_mock.calls) == 1
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=CRITERIA_KIND,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is True
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == api_returned_payload
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
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

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
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_no_retry_on_exception(self, caplog, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
            side_effect=TypeError("Programming error")
        )
        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        assert "TypeError: Programming error" in caplog.text
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])
