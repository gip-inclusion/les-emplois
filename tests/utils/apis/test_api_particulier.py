import httpx
import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.asp.models import Commune
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.tasks import certify_criterion_with_api_particulier
from itou.utils import triggers
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import (
    RESPONSES,
    ResponseKind,
)
from itou.utils.types import InclusiveDateRange
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


pytestmark = pytest.mark.usefixtures("api_particulier_settings")


def test_build_params_from(snapshot):
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True)
    job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
        "07141", job_seeker.jobseeker_profile.birthdate
    )
    with triggers.fake_context():
        job_seeker.jobseeker_profile.save(update_fields=["birth_place"])
    assert api_particulier._build_params_from(job_seeker) == snapshot(name="api_particulier_build_params")
    assert api_particulier.has_required_info(job_seeker) is True

    job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)
    assert api_particulier.has_required_info(job_seeker) is False

    job_seeker = JobSeekerFactory(born_outside_france=True)
    params = api_particulier._build_params_from(job_seeker)
    assert api_particulier.has_required_info(job_seeker) is True
    assert "codeCogInseeCommuneNaissance" not in params.keys()
    assert params["codeCogInseePaysNaissance"][2:] == job_seeker.jobseeker_profile.birth_country.code


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(IAEEligibilityDiagnosisFactory, id="iae"),
        pytest.param(GEIQEligibilityDiagnosisFactory, id="geiq"),
    ],
)
@pytest.mark.parametrize("criteria_kind", AdministrativeCriteriaKind.certifiable_by_api_particulier())
@freeze_time("2025-01-06")
def test_not_certified(criteria_kind, factory, respx_mock, caplog):
    eligibility_diagnosis = factory(
        certifiable=True,
        criteria_kinds=[criteria_kind],
        job_seeker__first_name="Jean",
        job_seeker__last_name="Dupont",
    )
    criterion = eligibility_diagnosis.selected_administrative_criteria.get()
    response = RESPONSES[criteria_kind][ResponseKind.NOT_CERTIFIED]
    respx_mock.get(settings.API_PARTICULIER_BASE_URL + api_particulier.ENDPOINTS[criteria_kind]).respond(
        status_code=response["status_code"], json=response["json"]
    )

    certify_criterion_with_api_particulier(criterion)

    assert len(respx_mock.calls) == 1
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.get(
        administrative_criteria__kind=criteria_kind,
        eligibility_diagnosis=eligibility_diagnosis,
    )
    assert criterion.certified_at == timezone.now()
    assert criterion.data_returned_by_api == response["json"]
    assert criterion.certification_period.isempty is True
    assert "https://fake-api-particulier.com/v3" in caplog.text
    assert "nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_" in caplog.text


def test_not_found(respx_mock, caplog):
    response = RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND]
    respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
        response["status_code"], json=response["json"]
    )
    diag = IAEEligibilityDiagnosisFactory(
        certifiable=True,
        criteria_kinds=[AdministrativeCriteriaKind.RSA],
        job_seeker__first_name="Jean",
        job_seeker__last_name="Dupont",
    )
    criterion = diag.selected_administrative_criteria.get()
    certify_criterion_with_api_particulier(criterion)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == response["json"]
    assert crit.certification_period == InclusiveDateRange(empty=True)
    assert "https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite" in caplog.text
    assert "nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_" in caplog.text


def test_http_status_error_does_not_leak_pii(respx_mock):
    """httpx builds HTTPStatusError's message from the URL, which identifies the job seeker."""
    respx_mock.get("https://fake-api-particulier.com/v3/dss/revenu_solidarite_active/identite").respond(
        502, text="Bad Gateway (non-JSON response)"
    )
    first_name, last_name = "Jean-Michel", "Tardiveau"
    job_seeker = JobSeekerFactory(first_name=first_name, last_name=last_name, born_in_france=True)

    with api_particulier.client() as client, pytest.raises(httpx.HTTPStatusError) as exc_info:
        api_particulier.certify_criteria(AdministrativeCriteriaKind.RSA, client, job_seeker)

    exception = exc_info.value
    assert "nomNaissance=_REDACTED_&prenoms%5B%5D=_REDACTED_" in str(exception)
    assert last_name.upper() not in str(exception).upper()
    assert first_name.upper() not in str(exception).upper()
    # the request the exception carries is redacted as well: Sentry serializes its repr
    assert last_name.upper() not in repr(exception.request).upper()
    assert last_name.upper() not in repr(exception.response.request).upper()
