import datetime
from json import JSONDecodeError

import httpx
import pytest
from django.conf import settings
from freezegun import freeze_time
from huey.exceptions import RetryTask
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models import EligibilityDiagnosis
from itou.eligibility.tasks import (
    async_certify_criteria_by_api_particulier,
    async_certify_criteria_by_api_pole_emploi,
    certify_criteria_by_api_particulier,
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
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory


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
        respx_mock.get(settings.API_PARTICULIER_BASE_URL + api_particulier.ENDPOINTS[criteria_kind]).respond(
            json=API_PARTICULIER_RESPONSES[criteria_kind][ApiParticulierResponseKind.CERTIFIED]
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
        assert (
            criterion.data_returned_by_api
            == API_PARTICULIER_RESPONSES[criteria_kind][ApiParticulierResponseKind.CERTIFIED]
        )
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
            async_certify_criteria_by_api_particulier.call_local(
                eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
            )
        # Huey catches the exception and retries the task.
        jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
        assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])

    def test_no_retry_on_exception(self, caplog, factory, respx_mock):
        eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
        respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").mock(
            side_effect=TypeError("Programming error")
        )
        async_certify_criteria_by_api_particulier.call_local(
            eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
        )
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

    def test_no_retries_when_diag_does_not_exist(self, caplog, factory):
        eligibility_diagnosis_model = factory._meta.model
        modelname = eligibility_diagnosis_model._meta.model_name
        async_certify_criteria_by_api_particulier.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]


class TestCertifyCriteriaPoleEmploi:
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

    @freeze_time("2025-09-15")
    def test_queue_task(self, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_pole_emploi(),
        )
        respx_mock.post("https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir").respond(
            200,
            json=API_POLE_EMPLOI_RESPONSES[PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR][
                ApiPoleEmploiResponseKind.CERTIFIED
            ],
        )
        json_response = API_POLE_EMPLOI_RESPONSES[PE_Endpoints.RQTH][ApiPoleEmploiResponseKind.CERTIFIED]
        certify_rqth_url = settings.API_ESD["BASE_URL"] + PE_Endpoints.RQTH
        respx_mock.get(certify_rqth_url).respond(200, json=json_response)

        async_certify_criteria_by_api_pole_emploi.call_local(
            eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
        )

        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            "https://pe.fake/rechercher-usager/v2/usagers/par-datenaissance-et-nir",
            certify_rqth_url,
        ]
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.get(eligibility_diagnosis=eligibility_diagnosis)
        assert criterion.certified is True
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

    @pytest.mark.parametrize(
        "response_kind",
        [
            ApiPoleEmploiResponseKind.MULTIPLE_USERS_RETURNED,
            ApiPoleEmploiResponseKind.NOT_CERTIFIED,
            ApiPoleEmploiResponseKind.NOT_FOUND,
        ],
    )
    def test_rechercher_usager_issues(self, caplog, response_kind, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_pole_emploi(),
        )
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        json_response = API_POLE_EMPLOI_RESPONSES[rechercher_usager_endpoint][response_kind]
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        respx_mock.post(rechercher_usager_url).respond(200, json=json_response)

        async_certify_criteria_by_api_pole_emploi.call_local(
            eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
        )

        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.get(eligibility_diagnosis=eligibility_diagnosis)
        assert criterion.certified is None
        assert criterion.certified_at is not None
        assert criterion.data_returned_by_api == json_response
        assert criterion.certification_period is None
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])
        assert f"Could not certify criterion {criterion!r}: json={json_response}" in caplog.messages

    def test_bad_response(self, caplog, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_pole_emploi(),
        )
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        json_response = API_POLE_EMPLOI_RESPONSES[rechercher_usager_endpoint][
            ApiPoleEmploiResponseKind.INTERNAL_SERVER_ERROR
        ]
        respx_mock.post(rechercher_usager_url).respond(500, json=json_response)

        with pytest.raises(httpx.HTTPError) as excinfo:
            async_certify_criteria_by_api_pole_emploi.call_local(
                eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
            )

        assert excinfo.value.response.status_code == 500
        assert excinfo.value.response.json() == json_response
        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.get(eligibility_diagnosis=eligibility_diagnosis)
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])

    def test_rate_limit(self, respx_mock):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
            certifiable=True,
            criteria_kinds=AdministrativeCriteriaKind.certifiable_by_api_pole_emploi(),
        )
        rechercher_usager_endpoint = PE_Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR
        rechercher_usager_url = f"https://pe.fake{rechercher_usager_endpoint}"
        respx_mock.post(rechercher_usager_url).respond(429, headers={"Retry-After": "42"})

        with pytest.raises(RetryTask) as excinfo:
            async_certify_criteria_by_api_pole_emploi.call_local(
                eligibility_diagnosis._meta.model_name, eligibility_diagnosis.pk
            )

        assert excinfo.value.delay == 42
        assert [call.request.url for call in respx_mock.calls] == [
            "https://auth.fr/connexion/oauth2/access_token?realm=%2Fagent",
            rechercher_usager_url,
        ]
        SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
        criterion = SelectedAdministrativeCriteria.objects.get(eligibility_diagnosis=eligibility_diagnosis)
        assert criterion.certified is None
        assert criterion.certified_at is None
        assert criterion.data_returned_by_api is None
        assert criterion.certification_period is None
        assertQuerySetEqual(eligibility_diagnosis.job_seeker.jobseeker_profile.identity_certifications.all(), [])

    def test_no_retries_when_diag_does_not_exist(self, caplog):
        modelname = EligibilityDiagnosis._meta.model_name
        async_certify_criteria_by_api_pole_emploi.call_local(modelname, 0)
        assert caplog.messages == [f"{modelname} with pk 0 does not exist, it cannot be certified."]
