from django.conf import settings

from itou.eligibility.tasks import certify_criteria
from itou.users.models import User
from itou.utils.apis import api_particulier
from itou.utils.mocks.api_particulier import rsa_data_provider_error, rsa_not_found_mocker
from tests.asp.factories import CommuneFactory, CountryFranceFactory, CountryOutsideEuropeFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import JobSeekerFactory


RSA_ENDPOINT = f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active"


def test_build_params_from(snapshot):
    birth_place = CommuneFactory(code="07141")
    job_seeker = JobSeekerFactory(born_in_france=True, for_snapshot=True, jobseeker_profile__birth_place=birth_place)
    job_seeker = User.objects.select_related(
        "jobseeker_profile", "jobseeker_profile__birth_place", "jobseeker_profile__birth_country"
    ).get(pk=job_seeker.pk)
    assert api_particulier._build_params_from(job_seeker) == snapshot(name="api_particulier_build_params")
    assert api_particulier.has_required_info(job_seeker) is True

    job_seeker = JobSeekerFactory(jobseeker_profile__birthdate=None)
    assert api_particulier.has_required_info(job_seeker) is False

    # Born in France without a birth country.
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=CountryFranceFactory(),
    )
    assert api_particulier.has_required_info(job_seeker) is False

    # Job seeker born outside of France
    country = CountryOutsideEuropeFactory()
    job_seeker = JobSeekerFactory(
        jobseeker_profile__birth_country=country,
    )
    params = api_particulier._build_params_from(job_seeker)
    assert api_particulier.has_required_info(job_seeker) is True
    assert "codeInseeLieuDeNaissance" not in params.keys()
    assert params["codePaysLieuDeNaissance"][2:] == country.code


def test_not_found(respx_mock):
    respx_mock.get(RSA_ENDPOINT).respond(404, json=rsa_not_found_mocker())
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    certify_criteria(diag)
    crit = diag.selected_administrative_criteria.get()
    assert crit.data_returned_by_api == rsa_not_found_mocker()
    assert crit.certified is None
    assert crit.certification_period is None


def test_service_unavailable(respx_mock, caplog):
    reason = "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service."
    respx_mock.get(RSA_ENDPOINT).respond(503, json=rsa_data_provider_error())
    diag = IAEEligibilityDiagnosisFactory(
        job_seeker__born_in_france=True,
        from_employer=True,
        with_certifiable_criteria=True,
    )
    certify_criteria(diag)
    assert reason in caplog.text
    assert RSA_ENDPOINT in caplog.text
