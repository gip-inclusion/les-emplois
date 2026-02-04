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
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger("APIParticulierClient")


def certify_criterion_with_api_particulier(criterion):
    if settings.API_PARTICULIER_BASE_URL is None:
        logging.info("API particulier is not configured, certification was skipped.")
        return
    job_seeker = criterion.eligibility_diagnosis.job_seeker
    if not api_particulier.has_required_info(job_seeker):
        logger.info("Skipping job seeker %s, missing required information.", job_seeker.pk)
        return

    criterion.last_certification_attempt_at = timezone.now()
    criterion.save(update_fields={"last_certification_attempt_at"})
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
                case 409:
                    # A request using the same token with same parameters is in progress.
                    raise RetryTask(delay=60) from exc
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
            start_at = data["start_at"]
            # The API can only tell whether the job seeker is beneficiary
            # on the day of the request.
            # Since we cannot tell when the certification expires, the
            # upper bound is set to None, and we rely on the expiry of
            # related objects (EligibilityDiagnosis) to actually expire a
            # SelectedAdministrativeCriteria.
            criterion.certification_period = (
                InclusiveDateRange(start_at) if criterion.certified else InclusiveDateRange(empty=True)
            )
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


# Retry for a long time, since the API particulier can only tell whether a job
# seeker benefits from a subsidy **on the day we call it**.
API_PARTICULIER_RETRY_DURATION = datetime.timedelta(days=1)
API_PARTICULIER_RETRY_DELAY = datetime.timedelta(minutes=10)
API_PARTICULIER_RETRY_COUNT = API_PARTICULIER_RETRY_DURATION / API_PARTICULIER_RETRY_DURATION


@on_commit_task(retries=API_PARTICULIER_RETRY_COUNT, retry_delay=API_PARTICULIER_RETRY_DURATION.total_seconds())
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
