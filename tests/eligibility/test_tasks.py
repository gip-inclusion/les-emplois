import copy
import datetime
from urllib.parse import urljoin

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models.iae import AdministrativeCriteria, SelectedAdministrativeCriteria
from itou.eligibility.tasks import (
    async_certify_criterion_with_api_particulier,
    async_certify_criterion_with_france_travail,
    certify_criterion_with_api_particulier,
)
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import JobSeekerProfile
from itou.utils.apis import api_particulier
from itou.utils.apis.pole_emploi import Endpoints as PE_Endpoints
from itou.utils.mocks.api_particulier import (
    RESPONSES as API_PARTICULIER_RESPONSES,
    ResponseKind as ApiParticulierResponseKind,
)
from itou.utils.mocks.pole_emploi import (
    RESPONSES as API_POLE_EMPLOI_RESPONSES,
    ResponseKind as ApiPoleEmploiResponseKind,
)
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
    IAESelectedAdministrativeCriteriaFactory,
)


def fake_response_code(response):
    response = copy.deepcopy(response)
    response["json"]["errors"][0]["code"] = "12345"
    return response


def fake_multiple_errors(response):
    response = copy.deepcopy(response)
    response["json"]["errors"].append(response["json"]["errors"][0])
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
    @pytest.mark.parametrize("criteria_kind", AdministrativeCriteriaKind.certifiable_by_api_particulier())
    @freeze_time("2025-01-06")
    def test_queue_task(self, criteria_kind, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[criteria_kind])
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        response = API_PARTICULIER_RESPONSES[criteria_kind][ApiParticulierResponseKind.CERTIFIED]
        respx_mock.get(settings.API_PARTICULIER_BASE_URL + api_particulier.ENDPOINTS[criteria_kind]).respond(
            status_code=response["status_code"], json=response["json"]
        )

        async_certify_criterion_with_api_particulier.call_local(criterion._meta.model_name, criterion.pk)

        criterion.refresh_from_db()
        assert len(respx_mock.calls) == 1
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == response["json"]
        assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
        # Was committed to the database.
        assert criterion.last_certification_attempt_at is not None
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
            criterion = eligibility_diagnosis.selected_administrative_criteria.get()
            respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            )

            with pytest.raises(RetryTask) as exc_info:
                async_certify_criterion_with_api_particulier.call_local(criterion._meta.model_name, criterion.pk)

            criterion.refresh_from_db()
            assert exc_info.value.delay == 1
            assert len(respx_mock.calls) == 1
            assert criterion.certified_at is None
            assert criterion.data_returned_by_api is None
            assert criterion.certification_period is None
            # Was committed to the database.
            assert criterion.last_certification_attempt_at is not None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    @pytest.mark.parametrize(
        "status_code,json_data,headers,retry_task_exception",
        [
            (400, {}, None, False),
            # "errors" is not in data, something went wrong, let the exception
            # bubble up for a retry.
            (404, {}, None, False),
            (
                API_PARTICULIER_RESPONSES[AdministrativeCriteriaKind.RSA][
                    ApiParticulierResponseKind.UNPROCESSABLE_CONTENT
                ]["status_code"],
                API_PARTICULIER_RESPONSES[AdministrativeCriteriaKind.RSA][
                    ApiParticulierResponseKind.UNPROCESSABLE_CONTENT
                ]["json"],
                None,
                None,
            ),
            (429, {}, None, False),
            (429, {}, {"Retry-After": "123"}, True),
            (502, {}, None, False),
        ],
    )
    def test_retry_task_on_http_error_status_codes(
        self, status_code, json_data, headers, retry_task_exception, factory, respx_mock
    ):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code, json=json_data, headers=headers
        )
        try:
            certify_criterion_with_api_particulier(criterion)
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
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        response = API_PARTICULIER_RESPONSES[AdministrativeCriteriaKind.RSA][
            ApiParticulierResponseKind.PROVIDER_UNKNOWN_ERROR
        ]
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code=response["status_code"], json=response["json"]
        )
        # Does not raise a RetryTask, this specific error is ignored.
        async_certify_criterion_with_api_particulier.call_local(criterion._meta.model_name, criterion.pk)
        assert len(respx_mock.calls) == 1
        criterion.refresh_from_db()
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api == response["json"]
        assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    @pytest.mark.parametrize("mutate_response", [fake_response_code, fake_multiple_errors])
    def test_raises_on_api_particulier_internal_error_with_unknown_error_code(
        self, factory, mutate_response, respx_mock
    ):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        response = mutate_response(
            API_PARTICULIER_RESPONSES[AdministrativeCriteriaKind.RSA][
                ApiParticulierResponseKind.PROVIDER_UNKNOWN_ERROR
            ]
        )
        respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
            status_code=response["status_code"], json=response["json"]
        )
        with pytest.raises(httpx.HTTPStatusError):
            async_certify_criterion_with_api_particulier.call_local(criterion._meta.model_name, criterion.pk)
        assert len(respx_mock.calls) == 1
        criterion.refresh_from_db()
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_no_retries_when_criterion_does_not_exist(self, caplog, factory):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        modelname = criterion._meta.model_name
        async_certify_criterion_with_api_particulier.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]


class TestCertifyCriteriaWithFranceTravail:
    @pytest.fixture(autouse=True)
    def mock_api(self, respx_mock, settings):
        settings.API_ESD = {
            "BASE_URL": "https://pe.fake",
            "AUTH_BASE_URL_AGENT": "https://auth.fr",
            "KEY": "foobar",
            "SECRET": "pe-secret",
        }
        respx_mock.post("https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent").respond(
            200, json={"token_type": "foo", "access_token": "batman", "expires_in": 3600}
        )

    @pytest.mark.parametrize(
        "job_seeker_kwargs",
        (
            {"nir": ""},
            {"birthdate": None},
            {
                "nir": "",
                # Older format, see is_france_travail_id_format().
                "pole_emploi_id": "12345678",
            },
        ),
    )
    def test_skip_job_seeker_with_missing_info(self, caplog, job_seeker_kwargs):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_france_travail(),
            **{f"job_seeker__jobseeker_profile__{k}": v for k, v in job_seeker_kwargs.items()},
        )
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()

        async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        criterion.refresh_from_db()
        assert criterion.certified_at is None
        assert (
            f"Skipping job seeker {eligibility_diagnosis.job_seeker_id}, missing required information "
            "for API France Travail." in caplog.messages
        )

    @pytest.mark.parametrize(
        "job_seeker_kwargs,endpoint",
        [
            pytest.param({}, PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR, id="date_naissance_nir"),
            pytest.param(
                {
                    "job_seeker__jobseeker_profile__nir": "",
                    "job_seeker__jobseeker_profile__birthdate": None,
                    "job_seeker__jobseeker_profile__pole_emploi_id": "12345678901",
                },
                PE_Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL,
                id="numero_francetravail",
            ),
        ],
    )
    @freeze_time("2025-09-15")
    def test_queue_task(self, respx_mock, job_seeker_kwargs, endpoint):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_france_travail(),
            **job_seeker_kwargs,
        )
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        rechercher_usager_url = urljoin("https://pe.fake", endpoint)
        respx_mock.post(rechercher_usager_url).respond(
            200, json=API_POLE_EMPLOI_RESPONSES[endpoint][ApiPoleEmploiResponseKind.CERTIFIED]
        )
        json_response = API_POLE_EMPLOI_RESPONSES[PE_Endpoints.RQTH][ApiPoleEmploiResponseKind.CERTIFIED]
        certify_rqth_url = settings.API_ESD["BASE_URL"] + PE_Endpoints.RQTH
        respx_mock.get(certify_rqth_url).respond(200, json=json_response)

        async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
            certify_rqth_url,
        ]
        criterion.refresh_from_db()
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == json_response
        assert criterion.certification_period == InclusiveDateRange(
            datetime.date(2024, 1, 20), datetime.date(2030, 1, 20)
        )
        assertQuerySetEqual(
            eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(),
            [IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER],
            transform=lambda certification: certification.certifier,
        )

    @freeze_time("2025-09-15")
    def test_not_certified(self, respx_mock):
        criterion = IAESelectedAdministrativeCriteriaFactory(
            administrative_criteria=AdministrativeCriteria.objects.get(
                kind__in=AdministrativeCriteriaKind.certifiable_by_api_france_travail()
            )
        )
        respx_mock.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200,
            json=API_POLE_EMPLOI_RESPONSES[PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][
                ApiPoleEmploiResponseKind.CERTIFIED
            ],
        )
        json_response = API_POLE_EMPLOI_RESPONSES[PE_Endpoints.RQTH][ApiPoleEmploiResponseKind.NOT_CERTIFIED]
        certify_rqth_url = settings.API_ESD["BASE_URL"] + PE_Endpoints.RQTH
        respx_mock.get(certify_rqth_url).respond(200, json=json_response)

        async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir",
            certify_rqth_url,
        ]
        eligibility_diagnosis = criterion.eligibility_diagnosis
        criterion.refresh_from_db()
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == json_response
        assert criterion.certification_period == InclusiveDateRange(empty=True)
        assertQuerySetEqual(
            eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(),
            [IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER],
            transform=lambda certification: certification.certifier,
        )

    @pytest.mark.parametrize(
        "response_kind,certification_period,user_found",
        [
            pytest.param(ApiPoleEmploiResponseKind.MULTIPLE_USERS_RETURNED, None, False, id="multiple-users"),
            pytest.param(ApiPoleEmploiResponseKind.NOT_FOUND, None, False, id="no-user"),
            pytest.param(
                ApiPoleEmploiResponseKind.NOT_CERTIFIED,
                InclusiveDateRange(empty=True),
                True,
                id="not-certified",
            ),
        ],
    )
    def test_rechercher_usager_issues(self, caplog, certification_period, response_kind, respx_mock, user_found):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_france_travail(),
        )
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        json_response = API_POLE_EMPLOI_RESPONSES[rechercher_usager_endpoint][response_kind]
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        respx_mock.post(rechercher_usager_url).respond(200, json=json_response)

        async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        criterion.refresh_from_db()
        assert (criterion.certified_at is not None) == user_found
        assert criterion.data_returned_by_api == json_response
        assert criterion.certification_period == certification_period
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])
        if response_kind == ApiPoleEmploiResponseKind.NOT_CERTIFIED:
            assert (
                f"Could not certify job seeker {eligibility_diagnosis.job_seeker_id}: json={json_response}"
                in caplog.messages
            )
        else:
            assert f"Could not certify criterion {criterion!r}: json={json_response}" in caplog.messages

    def test_bad_response(self, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_france_travail(),
        )
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        json_response = API_POLE_EMPLOI_RESPONSES[rechercher_usager_endpoint][
            ApiPoleEmploiResponseKind.INTERNAL_SERVER_ERROR
        ]
        respx_mock.post(rechercher_usager_url).respond(500, json=json_response)

        with pytest.raises(httpx.HTTPError) as excinfo:
            async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        assert excinfo.value.response.status_code == 500
        assert excinfo.value.response.json() == json_response
        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        criterion.refresh_from_db()
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])

    def test_rate_limit(self, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_france_travail(),
        )
        criterion = eligibility_diagnosis.selected_administrative_criteria.get()
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        respx_mock.post(rechercher_usager_url).respond(429, headers={"Retry-After": "42"})

        with pytest.raises(RetryTask) as excinfo:
            async_certify_criterion_with_france_travail.call_local(criterion._meta.model_name, criterion.pk)

        assert excinfo.value.delay == 42
        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        criterion.refresh_from_db()
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])

    def test_no_retries_when_diag_does_not_exist(self, caplog):
        modelname = SelectedAdministrativeCriteria._meta.model_name
        async_certify_criterion_with_france_travail.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]
