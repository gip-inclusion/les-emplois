import datetime
import logging
from json import JSONDecodeError

import httpx
from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import on_commit_task
from huey.exceptions import RetryTask

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from itou.utils.apis import api_particulier
from itou.utils.apis.pole_emploi import (
    IdentityNotCertified,
    MultipleUsersReturned,
    PoleEmploiAPIBadResponse,
    UserDoesNotExist,
    pole_emploi_agent_api_client,
)
from itou.utils.enums import ItouEnvironment
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger(__name__)


def certify_criteria_by_api_particulier(eligibility_diagnosis):
    if settings.ITOU_ENVIRONMENT == ItouEnvironment.DEV:
        logging.info(
            "API particulier is not configured in %s, certification was skipped.",
            settings.ITOU_ENVIRONMENT,
        )
        return
    job_seeker = eligibility_diagnosis.job_seeker
    if not api_particulier.has_required_info(job_seeker):
        logger.info("Skipping job seeker %s, missing required information.", job_seeker.pk)
        return
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criteria = (
        SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=AdministrativeCriteriaKind.certifiable_by_api_particulier(),
            eligibility_diagnosis=eligibility_diagnosis,
        )
        .select_for_update(of=("self",), no_key=True)
        .select_related("administrative_criteria")
    )
    with api_particulier.client() as client:
        for criterion in criteria:
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
                        # We sometimes get a 409 for some reason and the returned error message is not very helpful:
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

    SelectedAdministrativeCriteria.objects.bulk_update(
        criteria,
        fields=[
            "certification_period",
            "certified",
            "certified_at",
            "data_returned_by_api",
        ],
    )
    if any(c.certified is not None for c in criteria):
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_PARTICULIER,
                    jobseeker_profile=job_seeker.jobseeker_profile,
                    certified_at=max(c.certified_at for c in criteria),
                ),
            ]
        )


def certify_criteria_by_api_pole_emploi(eligibility_diagnosis):
    if settings.ITOU_ENVIRONMENT == ItouEnvironment.DEV:
        logging.info(
            "API France Travail is not configured in %s, certify_criteria_pole_emploi was skipped.",
            settings.ITOU_ENVIRONMENT,
        )
        return
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    job_seeker = eligibility_diagnosis.job_seeker
    criterion = (
        SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=AdministrativeCriteriaKind.certifiable_by_api_pole_emploi(),
            eligibility_diagnosis=eligibility_diagnosis,
        )
        .select_for_update(of=("self",), no_key=True)
        .get()
    )
    with pole_emploi_agent_api_client() as pe_client:
        try:
            data = pe_client.certify_rqth(jobseeker_profile=job_seeker.jobseeker_profile)
        except (IdentityNotCertified, MultipleUsersReturned, UserDoesNotExist) as e:
            logger.info("Could not certify criterion %r: json=%s", criterion, e.response_data)
            criterion.data_returned_by_api = e.response_data
        except PoleEmploiAPIBadResponse as e:
            logger.error("Error certifying criterion %r: code=%d json=%s", criterion, e.response_code, e.response_data)
            criterion.data_returned_by_api = e.response_data
        except httpx.HTTPError as e:
            if e.response.status_code == 429:
                # https://francetravail.io/produits-partages/documentation/utilisation-api-france-travail/erreurs-frequentes#:~:text=429 Too Many Requests  # noqa: E501
                raise RetryTask(delay=int(e.response.headers["Retry-After"])) from e
            raise e
        else:
            criterion.certified = data["is_certified"]
            criterion.data_returned_by_api = data["raw_response"]
            if criterion.certified:
                criterion.certification_period = InclusiveDateRange(data["start_at"], data["end_at"])
    criterion.certified_at = timezone.now()
    criterion.save(
        update_fields=[
            "certification_period",
            "certified",
            "certified_at",
            "data_returned_by_api",
        ]
    )
    if criterion.certified is not None:
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_FT_RECHERCHER_USAGER,
                    jobseeker_profile=job_seeker.jobseeker_profile,
                    certified_at=criterion.certified_at,
                ),
            ],
        )


def _async_certify_criteria(model_name, eligibility_diagnosis_pk, *, certify_func):
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
            certify_func(eligibility_diagnosis)
    except (
        httpx.HTTPError,  # Could not connect, unexpected status code, …
        JSONDecodeError,  # Response was not JSON (text, HTML, …).
        RetryTask,  # Rate limiting.
    ):
        # Worth retrying.
        raise
    except Exception as e:
        logger.exception(e)


def _async_certify_criteria_by_api_particulier(model_name, eligibility_diagnosis_pk):
    _async_certify_criteria(model_name, eligibility_diagnosis_pk, certify_func=certify_criteria_by_api_particulier)


def _async_certify_criteria_by_api_pole_emploi(model_name, eligibility_diagnosis_pk):
    _async_certify_criteria(model_name, eligibility_diagnosis_pk, certify_func=certify_criteria_by_api_pole_emploi)


# Retry every 10 minutes for 24h.
async_certify_criteria_by_api_particulier = on_commit_task(retries=24 * 6, retry_delay=10 * 60)(
    _async_certify_criteria_by_api_particulier
)
async_certify_criteria_by_api_pole_emploi = on_commit_task(retries=24 * 6, retry_delay=10 * 60)(
    _async_certify_criteria_by_api_pole_emploi
)
# TODO(François): Legacy task definition, drop at least 24h after it has been deployed.
async_certify_criteria = on_commit_task(
    retries=24 * 6,
    retry_delay=10 * 60,
    name="_async_certify_criteria",
)(_async_certify_criteria_by_api_particulier)
# TODO: Use the decorator and drop assignment of call_local if
# https://github.com/coleifer/huey/pull/848 is integrated.
async_certify_criteria_by_api_particulier.call_local = _async_certify_criteria_by_api_particulier
async_certify_criteria_by_api_pole_emploi.call_local = _async_certify_criteria_by_api_pole_emploi
