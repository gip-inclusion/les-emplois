import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.asp.models import Commune
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criteria
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    aah_not_certified_mocker,
    rsa_data_provider_error,
    rsa_not_certified_mocker,
    rsa_not_found_mocker,
)
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
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
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
@pytest.mark.parametrize(
    "endpoint,CRITERIA_KIND,api_returned_payload",
    [
        pytest.param(
            f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active",
            AdministrativeCriteriaKind.RSA,
            rsa_not_certified_mocker(),
            id="rsa",
        ),
        pytest.param(
            f"{settings.API_PARTICULIER_BASE_URL}v2/allocation-adulte-handicape",
            AdministrativeCriteriaKind.AAH,
            aah_not_certified_mocker(),
            id="aah",
        ),
    ],
)
@freeze_time("2025-01-06")
def test_not_certified(endpoint, CRITERIA_KIND, api_returned_payload, factory, respx_mock):
    eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[CRITERIA_KIND])
    respx_mock.get(endpoint).respond(json=api_returned_payload)

    eligibility_diagnosis.certify_criteria()

    assert len(respx_mock.calls) == 1
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.get(
        administrative_criteria__kind=CRITERIA_KIND,
        eligibility_diagnosis=eligibility_diagnosis,
    )
    assert criterion.certified is False
    assert criterion.certified_at == timezone.now()
    assert criterion.data_returned_by_api == api_returned_payload
    assert criterion.certification_period is None


def test_not_found(respx_mock, caplog):
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        404, json=rsa_not_found_mocker()
    )
    diag = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == rsa_not_found_mocker()
    assert crit.certified is None
    assert crit.certification_period is None
    assert "Dossier allocataire inexistant. Le document ne peut être édité." in caplog.text
    assert f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active" in caplog.text


def test_service_unavailable(respx_mock, caplog):
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        503, json=rsa_data_provider_error()
    )
    diag = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == rsa_data_provider_error()
    assert crit.certified is None
    assert crit.certification_period is None
    assert (
        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service." in caplog.text
    )
    assert f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active" in caplog.text
