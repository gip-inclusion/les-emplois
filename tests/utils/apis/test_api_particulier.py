import pytest
from django.conf import settings

from itou.asp.models import Commune
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criteria
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import rsa_data_provider_error, rsa_not_found_mocker
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


def test_build_params_from(snapshot):
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True)
    job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
        "07141", job_seeker.jobseeker_profile.birthdate
    )
    job_seeker.jobseeker_profile.save(update_fields=["birth_place"])
    assert api_particulier._build_params_from(job_seeker) == snapshot(name="api_particulier_build_params")
    assert api_particulier.has_required_info(job_seeker) is True

    job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)
    assert api_particulier.has_required_info(job_seeker) is False

    job_seeker = JobSeekerFactory(born_outside_france=True)
    params = api_particulier._build_params_from(job_seeker)
    assert api_particulier.has_required_info(job_seeker) is True
    assert "codeInseeLieuDeNaissance" not in params.keys()
    assert params["codePaysLieuDeNaissance"][2:] == job_seeker.jobseeker_profile.birth_country.code


@pytest.mark.parametrize(
    "endpoint,CRITERIA_KIND,api_returned_payload",
    [
        pytest.param(
            f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active",
            AdministrativeCriteriaKind.RSA,
            rsa_not_found_mocker(),
            id="test_not_found_rsa",
        ),
    ],
)
def test_not_found(respx_mock, caplog, endpoint, CRITERIA_KIND, api_returned_payload):
    respx_mock.get(endpoint).respond(404, json=api_returned_payload)
    diag = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[CRITERIA_KIND])
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == api_returned_payload
    assert crit.certified is None
    assert crit.certification_period is None
    assert "Dossier allocataire inexistant. Le document ne peut être édité." in caplog.text
    assert endpoint in caplog.text


@pytest.mark.parametrize(
    "endpoint,CRITERIA_KIND,api_returned_payload",
    [
        pytest.param(
            f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active",
            AdministrativeCriteriaKind.RSA,
            rsa_data_provider_error(),
            id="test_service_unavailable_rsa",
        ),
    ],
)
def test_service_unavailable(respx_mock, caplog, endpoint, CRITERIA_KIND, api_returned_payload):
    respx_mock.get(endpoint).respond(503, json=api_returned_payload)
    diag = IAEEligibilityDiagnosisFactory(criteria_kinds=[CRITERIA_KIND], certifiable=True)
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == api_returned_payload
    assert crit.certified is None
    assert crit.certification_period is None
    assert (
        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service." in caplog.text
    )
    assert endpoint in caplog.text
