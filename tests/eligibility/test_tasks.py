import datetime
import itertools
from json import JSONDecodeError

import httpx
import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time
from huey.exceptions import RetryTask
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import async_certify_criteria, certify_criteria
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import JobSeekerProfile
from itou.utils.mocks import api_particulier as api_particulier_mocks, pole_emploi as pole_emploi_mocks
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


def _pe_api_request_auth_and_rechercher_usager(respx_mock):
    respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent").respond(
        200, json={"token_type": "foo", "access_token": "Catwman", "expires_in": 3600}
    )
    respx_mock.post(pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]).respond(
        json=pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]][
            pole_emploi_mocks.ResponseKind.CERTIFIED
        ]
    )


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
class TestCertifyCriteria:
    @pytest.mark.parametrize(
        "criteria_kind,certification_authority",
        [
            *zip(
                AdministrativeCriteriaKind.certifiable_by_api_particulier(),
                itertools.repeat(IdentityCertificationAuthorities.API_PARTICULIER),
            ),
            *zip(
                AdministrativeCriteriaKind.certifiable_by_pole_emploi_api(),
                itertools.repeat(IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER),
            ),
        ],
    )
    @freeze_time("2025-01-06")
    def test_queue_task(self, criteria_kind, certification_authority, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[criteria_kind])
        if criteria_kind in AdministrativeCriteriaKind.certifiable_by_api_particulier():
            expected_certification_period = InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2025, 4, 8))
            data_returned_by_api = api_particulier_mocks.RESPONSES[criteria_kind][
                api_particulier_mocks.ResponseKind.CERTIFIED
            ]
            respx_mock.get(api_particulier_mocks.ENDPOINTS[criteria_kind]).respond(json=data_returned_by_api)

        if criteria_kind == AdministrativeCriteriaKind.TH:
            # TH administrative criteria does not benefit from a grace period.
            expected_certification_period = InclusiveDateRange(datetime.date(2024, 1, 20), datetime.date(2025, 4, 8))
            _pe_api_request_auth_and_rechercher_usager(respx_mock)
            data_returned_by_api = pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rqth"]][
                pole_emploi_mocks.ResponseKind.CERTIFIED
            ]
            respx_mock.get(pole_emploi_mocks.ENDPOINTS["rqth"]).respond(json=data_returned_by_api)

        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

        assert len(respx_mock.calls) == len(respx_mock.routes)
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=criteria_kind,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is True
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == data_returned_by_api
        assert criterion.certification_period == expected_certification_period
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(
            jobseeker_profile.identity_certifications.all(),
            [certification_authority],
            transform=lambda certification: certification.certifier,
        )


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
class TestCertifyCriteriaApiParticulier:
    def test_retry_task_rate_limits(self, factory, respx_mock):
        # The API returns the same error messages for each endpoint called by us.
        # It would be useless to test them all.
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

    @pytest.mark.parametrize(
        "status_code,json_data,headers,retry_task_exception",
        [
            (400, {}, None, None),
            (409, {}, None, True),
            (429, {}, None, False),
            (429, {}, {"Retry-After": "123"}, True),
            (503, {}, None, False),
            (
                503,
                {
                    "message": (
                        "Erreur de fournisseur de donnée : Trop de requêtes effectuées, veuillez réessayer plus tard."
                    ),
                },
                None,
                True,
            ),
            (503, {"message": "Déso"}, None, None),
        ],
    )
    def test_retry_task_on_http_error_status_codes(
        self, status_code, json_data, headers, retry_task_exception, factory, respx_mock
    ):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
            status_code, json=json_data, headers=headers
        )
        try:
            certify_criteria(eligibility_diagnosis)
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

    def test_no_retries_when_diag_does_not_exist(self, caplog, factory):
        eligibility_diagnosis_model = factory._meta.model
        modelname = eligibility_diagnosis_model._meta.model_name
        async_certify_criteria.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
class TestCertifyCriteriaPoleEmploiAPI:
    def test_retry_on_pole_emploi_rate_limit_exception(self, factory, respx_mock):
        # The API returns the same error messages for each endpoint called by us.
        # It would be useless to test them all.
        with freeze_time("2024-09-12T00:00:00Z"):
            eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.TH])
            _pe_api_request_auth_and_rechercher_usager(respx_mock)
            respx_mock.get(pole_emploi_mocks.ENDPOINTS["rqth"]).respond(
                status_code=429,
            )

            with pytest.raises(RetryTask) as exc_info:
                async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

            assert exc_info.value.delay == 3600
            assert len(respx_mock.calls) == 3
            SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
            criterion = SelectedAdministrativeCriteria.objects.filter(
                administrative_criteria__kind=AdministrativeCriteriaKind.TH,
                eligibility_diagnosis=eligibility_diagnosis,
            ).get()
            assert criterion.certified is None
            assert criterion.certified_at is None
            assert criterion.data_returned_by_api is None
            assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_retry_task_on_pole_emploi_api_exception(self, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.TH])
        _pe_api_request_auth_and_rechercher_usager(respx_mock)
        respx_mock.get(pole_emploi_mocks.ENDPOINTS["rqth"]).respond(
            status_code=500,
            json=pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]][
                pole_emploi_mocks.ResponseKind.INTERNAL_SERVER_ERROR
            ],
        )
        with pytest.raises(RetryTask):
            async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        # Huey catches the exception and retries the task.
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    # TODO(cms) Also test 400 and 401?
    @pytest.mark.parametrize(
        "status_code,exception,response",
        [
            pytest.param(
                403,
                "PoleEmploiAPIBadResponse",
                pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]][
                    pole_emploi_mocks.ResponseKind.FORBIDDEN
                ],
                id="403",
            ),
            pytest.param(
                403,
                "PoleEmploiAPIBadResponse",
                pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]][
                    pole_emploi_mocks.ResponseKind.BAD_REQUEST
                ],
                id="400",
            ),
        ],
    )
    def test_no_retry_on_exception(self, caplog, factory, respx_mock, status_code, exception, response):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.TH])
        _pe_api_request_auth_and_rechercher_usager(respx_mock)
        respx_mock.get(pole_emploi_mocks.ENDPOINTS["rqth"]).respond(status_code=status_code, json=response)
        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        assert "Error certifying criterion" in caplog.text
        assert exception in caplog.text

        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind=AdministrativeCriteriaKind.TH,
            eligibility_diagnosis=eligibility_diagnosis,
        ).get()
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api == response
        assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    @pytest.mark.parametrize(
        "response_kind",
        [
            pole_emploi_mocks.ResponseKind.MULTIPLE_USERS_RETURNED,
            pole_emploi_mocks.ResponseKind.NOT_CERTIFIED,
            pole_emploi_mocks.ResponseKind.NOT_FOUND,
        ],
    )
    def test_no_retry_on_user_exception(self, caplog, factory, respx_mock, response_kind):
        with freeze_time("2024-09-12T00:00:00Z"):
            eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.TH])
            respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent").respond(
                200, json={"token_type": "foo", "access_token": "Catwman", "expires_in": 3600}
            )
            data = pole_emploi_mocks.RESPONSES[pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]][
                response_kind
            ]
            respx_mock.post(pole_emploi_mocks.ENDPOINTS["rechercher-usager-date-naissance-nir"]).respond(json=data)
            async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)

            jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
            assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])
            SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
            criterion = SelectedAdministrativeCriteria.objects.filter(
                administrative_criteria__kind=AdministrativeCriteriaKind.TH,
                eligibility_diagnosis=eligibility_diagnosis,
            ).get()
            assert criterion.certified is None
            assert criterion.certified_at == timezone.now()
            assert criterion.data_returned_by_api == data
            assert criterion.certification_period is None
            jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
            assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_no_retry_on_missing_profile_information(self, factory, respx_mock, caplog):
        eligibility_diagnosis = factory(
            certifiable=True,
            job_seeker__jobseeker_profile__nir="",
            job_seeker__jobseeker_profile__pole_emploi_id="",
            criteria_kinds=[AdministrativeCriteriaKind.TH],
        )
        async_certify_criteria.call_local(eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk)
        assert len(respx_mock.calls) == 0
        assert (
            f"Skipping job seeker {eligibility_diagnosis.job_seeker.pk}, missing required information." in caplog.text
        )
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])
