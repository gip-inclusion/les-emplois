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
from itou.utils.enums import ItouEnvironment
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger("APIParticulierClient")


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
                match exc.response.status_code:
                    case (
                        # Identity found, but not attached to a data provider
                        # (no “caisse de rattachement”, or no entry for that
                        # person in the “caisse de rattachement”).
                        404
                        # Identity not found, change the query parameters.
                        | 422
                    ):
                        if "errors" not in criterion.data_returned_by_api:
                            raise
                        criterion.certified_at = timezone.now()
                    case 429:
                        # https://particulier.api.gouv.fr/developpeurs#respecter-la-volumétrie
                        raise RetryTask(delay=int(exc.response.headers["Retry-After"])) from exc
                    case 502:
                        if len(criterion.data_returned_by_api["errors"]) == 1 and criterion.data_returned_by_api[
                            "errors"
                        ][0]["code"] in {
                            api_particulier.UNKNOWN_RESPONSE_FROM_PROVIDER_CNAV_ERROR_CODE,
                            api_particulier.UNKNOWN_RESPONSE_FROM_PROVIDER_SECURITE_SOCIALE_ERROR_CODE,
                        }:
                            # Retrying won’t fix the issue.
                            logger.info(
                                "Error certifying criterion %r, API Particulier got an unknown response "
                                "from the data provider.",
                                criterion,
                            )
                        else:
                            raise
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


def _async_certify_criteria_by_api_particulier(model_name, eligibility_diagnosis_pk):
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
            certify_criteria_by_api_particulier(eligibility_diagnosis)
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
async_certify_criteria_by_api_particulier = on_commit_task(retries=24 * 6, retry_delay=10 * 60)(
    _async_certify_criteria_by_api_particulier
)
# TODO: Use the decorator and drop assignment of call_local if
# https://github.com/coleifer/huey/pull/848 is integrated.
async_certify_criteria_by_api_particulier.call_local = _async_certify_criteria_by_api_particulier
