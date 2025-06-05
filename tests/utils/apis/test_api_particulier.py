import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.asp.models import Commune
from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criteria
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    ENDPOINTS,
    RESPONSES,
    ResponseKind,
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
@pytest.mark.parametrize("criteria_kind", CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS)
@freeze_time("2025-01-06")
def test_not_certified(criteria_kind, factory, respx_mock):
    eligibility_diagnosis = factory(certifiable=True, criteria_kinds=[criteria_kind])
    respx_mock.get(ENDPOINTS[criteria_kind]).respond(json=RESPONSES[criteria_kind][ResponseKind.NOT_CERTIFIED])

    eligibility_diagnosis.certify_criteria()

    assert len(respx_mock.calls) == 1
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.get(
        administrative_criteria__kind=criteria_kind,
        eligibility_diagnosis=eligibility_diagnosis,
    )
    assert criterion.certified is False
    assert criterion.certified_at == timezone.now()
    assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.NOT_CERTIFIED]
    assert criterion.certification_period is None


def test_not_found(respx_mock, caplog):
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        404, json=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND]
    )
    diag = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND]
    assert crit.certified is None
    assert crit.certification_period is None
    assert "Dossier allocataire inexistant. Le document ne peut être édité." in caplog.text
    assert f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active" not in caplog.text


def test_service_unavailable(respx_mock, caplog):
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        503, json=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.PROVIDER_UNKNOWN_ERROR]
    )
    diag = IAEEligibilityDiagnosisFactory(certifiable=True, criteria_kinds=[AdministrativeCriteriaKind.RSA])
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.PROVIDER_UNKNOWN_ERROR]
    assert crit.certified is None
    assert crit.certification_period is None
    assert (
        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service." in caplog.text
    )
    assert f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active" not in caplog.text
