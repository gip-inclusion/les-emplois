import datetime
import logging
from json import JSONDecodeError

import httpx
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import on_commit_task
from huey.exceptions import RetryTask

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from itou.utils.apis import api_particulier, pole_emploi as pole_emploi_api
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger("APIParticulierClient")


def certify_criteria(eligibility_diagnosis):
    job_seeker = eligibility_diagnosis.job_seeker
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criteria = (
        SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
            eligibility_diagnosis=eligibility_diagnosis,
        )
        .select_for_update(of=("self",), no_key=True)
        .select_related("administrative_criteria")
    )
    criteria_certifiable_by_api_particulier = [
        criterion
        for criterion in criteria
        if criterion.administrative_criteria.kind in AdministrativeCriteriaKind.certifiable_by_api_particulier()
    ]
    if criteria_certifiable_by_api_particulier:
        if not api_particulier.has_required_info(job_seeker):
            logger.info("Skipping job seeker %s, missing required information.", job_seeker.pk)
            return
        with api_particulier.client() as client:
            for criterion in criteria_certifiable_by_api_particulier:
                try:
                    data = api_particulier.certify_criteria(criterion.administrative_criteria.kind, client, job_seeker)
                except httpx.HTTPStatusError as exc:
                    criterion.data_returned_by_api = exc.response.json()
                    logger.error(
                        "Error certifying criterion %r: code=%d json=%s",
                        criterion,
                        exc.response.status_code,
                        criterion.data_returned_by_api,
                    )
                    match exc.response.status_code:
                        case 400 | 404:
                            # Job seeker not found or missing profile information.
                            criterion.certified_at = timezone.now()
                        case 409:
                            # We sometimes get a 409 for some reason and the returned error message is not very
                            # helpful:
                            # "Une requête associé à votre jeton est déjà en cours de traitement
                            #  pour ces paramètres. Veuillez attendr..."
                            # Since we don't want the request URL with personal data to be logged
                            # we simply retry later
                            raise RetryTask(delay=5) from exc
                        case 429:
                            # https://particulier.api.gouv.fr/developpeurs#respecter-la-volumétrie
                            raise RetryTask(delay=int(exc.response.headers["Retry-After"])) from exc
                        case 503:
                            # TODO: Use the error code instead of the message when switching to API v3.
                            if criterion.data_returned_by_api["message"] == (
                                "Erreur de fournisseur de donnée : "
                                "Trop de requêtes effectuées, veuillez réessayer plus tard."
                            ):
                                # The data provider for API particulier returned a 429.
                                # Let’s hope the data provider rate limit has been reset by then.
                                raise RetryTask(delay=3600) from exc
                            else:
                                # The data provider for API particulier likely returned a 500.
                                # According to the API particulier team, it often means integrity
                                # errors on the beneficiary case. The data provider itself aggregates data
                                # from other providers (e.g. regional information systems). When the data
                                # sources aren’t consistent with each other, the data provider cannot
                                # answer.
                                # Retrying won’t fix the issue, and the error has been logged already.
                                pass
                        case _:
                            raise
                else:
                    criterion.certified = data["is_certified"]
                    criterion.certified_at = timezone.now()
                    criterion.data_returned_by_api = data["raw_response"]
                    criterion.certification_period = None
                    if criterion.certified:
                        start_at = data["start_at"]
                        end_at = timezone.localdate(criterion.certified_at) + datetime.timedelta(
                            days=criterion.CERTIFICATION_GRACE_PERIOD_DAYS
                        )
                        criterion.certification_period = InclusiveDateRange(start_at, end_at)

    criteria_certifiable_by_pole_emploi_api = [
        criterion
        for criterion in criteria
        if criterion.administrative_criteria.kind in AdministrativeCriteriaKind.certifiable_by_pole_emploi_api()
    ]

    if criteria_certifiable_by_pole_emploi_api:
        with pole_emploi_api.pole_emploi_agent_api_client() as pe_client:
            for criterion in criteria_certifiable_by_pole_emploi_api:
                try:
                    data = pole_emploi_api.certify_criteria(
                        criterion_kind=criterion.administrative_criteria.kind,
                        jobseeker_profile=job_seeker.jobseeker_profile,
                        client=pe_client,
                    )
                except pole_emploi_api.PoleEmploiAPIBaseException as exc:
                    logger.error(
                        "Error certifying criterion %r: exc=%s json=%s",
                        criterion,
                        exc,
                        criterion.data_returned_by_api,
                    )
                    match type(exc):
                        case pole_emploi_api.JobSeekerProfileBadInformationError:
                            logger.info("Skipping job seeker %s, missing required information.", job_seeker.pk)
                            return
                        case pole_emploi_api.PoleEmploiRateLimitException:
                            raise RetryTask(delay=3600) from exc
                        case (
                            pole_emploi_api.MultipleUsersReturned
                            | pole_emploi_api.UserDoesNotExist
                            | pole_emploi_api.IdentityNotCertified
                        ):
                            criterion.data_returned_by_api = exc.response_data
                            criterion.certified_at = timezone.now()
                        case pole_emploi_api.PoleEmploiAPIBadResponse:
                            criterion.data_returned_by_api = exc.response_data
                        case pole_emploi_api.PoleEmploiAPIException:
                            raise RetryTask(delay=3600) from exc
                else:
                    criterion.certified = data["is_certified"]
                    criterion.certified_at = timezone.now()
                    criterion.data_returned_by_api = data["raw_response"]
                    criterion.certification_period = None
                    if criterion.certified:
                        start_at = data["start_at"]
                        end_at = timezone.localdate(criterion.certified_at) + datetime.timedelta(
                            days=criterion.CERTIFICATION_GRACE_PERIOD_DAYS
                        )
                        criterion.certification_period = InclusiveDateRange(start_at, end_at)

    criteria = [*criteria_certifiable_by_api_particulier, *criteria_certifiable_by_pole_emploi_api]
    SelectedAdministrativeCriteria.objects.bulk_update(
        criteria,
        fields=[
            "certification_period",
            "certified",
            "certified_at",
            "data_returned_by_api",
        ],
    )
    if any(c.certified is not None for c in criteria_certifiable_by_api_particulier):
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_PARTICULIER,
                    jobseeker_profile=job_seeker.jobseeker_profile,
                    certified_at=max(c.certified_at for c in criteria_certifiable_by_api_particulier),
                ),
            ]
        )
    elif any(c.certified is not None for c in criteria_certifiable_by_pole_emploi_api):
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER,
                    jobseeker_profile=job_seeker.jobseeker_profile,
                    certified_at=max(c.certified_at for c in criteria_certifiable_by_pole_emploi_api),
                ),
            ]
        )


def _async_certify_criteria(model_name, eligibility_diagnosis_pk):
    model = apps.get_model("eligibility", model_name)
    try:
        eligibility_diagnosis = model.objects.select_related("job_seeker__jobseeker_profile").get(
            pk=eligibility_diagnosis_pk
        )
    except model.DoesNotExist:
        logger.info(
            "%s with pk %d does not exist, it cannot be certified.",
            model_name,
            eligibility_diagnosis_pk,
        )
        return
    try:
        with transaction.atomic():
            certify_criteria(eligibility_diagnosis)
    except (
        httpx.HTTPError,  # Could not connect, unexpected status code, …
        JSONDecodeError,  # Response was not JSON (text, HTML, …).
        RetryTask,  # Rate limiting.
    ):
        # Worth retrying.
        raise
    except Exception as e:
        logger.exception(e)


# Retry every 10 minutes for 24h.
async_certify_criteria = on_commit_task(retries=24 * 6, retry_delay=10 * 60)(_async_certify_criteria)
# TODO: Use the decorator and drop assignment of call_local if
# https://github.com/coleifer/huey/pull/848 is integrated.
async_certify_criteria.call_local = _async_certify_criteria
