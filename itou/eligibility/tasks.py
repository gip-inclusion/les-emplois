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

from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from itou.utils.apis import api_particulier
from itou.utils.enums import ItouEnvironment
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger("APIParticulierClient")


def certify_criterion_with_api_particulier(criterion):
    if settings.ITOU_ENVIRONMENT == ItouEnvironment.DEV:
        logging.info(
            "API particulier is not configured in %s, certification was skipped.",
            settings.ITOU_ENVIRONMENT,
        )
        return
    job_seeker = criterion.eligibility_diagnosis.job_seeker
    if not api_particulier.has_required_info(job_seeker):
        logger.info("Skipping job seeker %s, missing required information.", job_seeker.pk)
        return
    with api_particulier.client() as client:
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
                    if len(criterion.data_returned_by_api["errors"]) == 1 and criterion.data_returned_by_api["errors"][
                        0
                    ]["code"] in {
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
    with transaction.atomic():
        criterion.save()
        if criterion.certified is not None:
            IdentityCertification.objects.upsert_certifications(
                [
                    IdentityCertification(
                        certifier=IdentityCertificationAuthorities.API_PARTICULIER,
                        jobseeker_profile=job_seeker.jobseeker_profile,
                        certified_at=criterion.certified_at,
                    ),
                ]
            )


# Retry every 10 minutes for 24h.
@on_commit_task(retries=24 * 6, retry_delay=10 * 60)
def async_certify_criterion_with_api_particulier(model_name, selected_administrative_criteria_id):
    model = apps.get_model("eligibility", model_name)
    with transaction.atomic():
        try:
            criterion = (
                model.objects.select_related(
                    "eligibility_diagnosis__job_seeker__jobseeker_profile",
                    "administrative_criteria",
                )
                .select_for_update(of=("self",), no_key=True)
                .get(pk=selected_administrative_criteria_id)
            )
        except model.DoesNotExist:
            logger.info(
                "%s with pk %d does not exist, it cannot be certified.",
                model_name,
                selected_administrative_criteria_id,
            )
            return

        captured_exc = None
        retry = False
        try:
            certify_criterion_with_api_particulier(criterion)
        except (
            httpx.HTTPError,  # Could not connect, unexpected status code, …
            JSONDecodeError,  # Response was not JSON (text, HTML, …).
            RetryTask,  # Rate limiting.
        ) as e:
            retry = True
            captured_exc = e
        except Exception as e:
            retry = False
            captured_exc = e
    # Outer transaction committed, we can raise.
    if captured_exc:
        if retry:
            raise captured_exc
        logger.exception(captured_exc)
