import datetime
import json
import logging

import httpx
from django.apps import apps
from django.utils import timezone
from huey.contrib.djhuey import task
from huey.exceptions import RetryTask

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.utils.apis import api_particulier
from itou.utils.types import InclusiveDateRange


logger = logging.getLogger("APIParticulierClient")


def certify_criteria(eligibility_diagnosis):
    job_seeker = eligibility_diagnosis.job_seeker
    if not api_particulier.has_required_info(job_seeker):
        logger.info("Skipping {job_seeker.pk=}, missing required information.")
        return
    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criteria = (
        SelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=AdministrativeCriteriaKind.can_be_certified(),
            eligibility_diagnosis=eligibility_diagnosis,
        )
        .select_for_update(no_key=True)
        .select_related("administrative_criteria")
    )
    with api_particulier.client() as client:
        for criterion in criteria:
            # Only the RSA criterion is certifiable at the moment,
            # but this may change soon with the addition of `parent isolé` and `allocation adulte handicapé`.
            if criterion.administrative_criteria.kind == AdministrativeCriteriaKind.RSA:
                try:
                    data = api_particulier.revenu_solidarite_active(client, job_seeker)
                except httpx.HTTPStatusError as exc:
                    try:
                        criterion.data_returned_by_api = exc.response.json()
                    except json.decoder.JSONDecodeError:
                        logger.error("%d: %s", exc.response.status_code, exc.response.text)
                        raise RetryTask(delay=600) from exc
                    logger.error("%d: %s", exc.response.status_code, criterion.data_returned_by_api)
                    match exc.response.status_code:
                        case 400 | 404:
                            # Job seeker not found or missing profile information.
                            criterion.certified_at = timezone.now()
                        case 429 | 503:
                            # https://particulier.api.gouv.fr/developpeurs#respecter-la-volumétrie
                            try:
                                raise RetryTask(delay=int(exc.response.headers["Retry-After"])) from exc
                            except (
                                KeyError,  # Missing header.
                                ValueError,  # Not an int.
                            ):
                                # Contrary to the (outdated) spec for this header,
                                # https://www.ietf.org/archive/id/draft-polli-ratelimit-headers-05.html#name-ratelimit-reset
                                # the API uses an integer that is the UNIX timestamp when the rate limit period ends.
                                reset_ts = datetime.datetime.fromtimestamp(
                                    int(exc.response.headers["RateLimit-Reset"]),
                                    datetime.UTC,
                                )
                                raise RetryTask(eta=reset_ts) from exc
                        case 500 | 504:
                            # Your guess is as good as mine.
                            raise RetryTask(delay=600) from exc
                        case _:
                            raise
                except httpx.HTTPError as exc:
                    raise RetryTask(delay=10) from exc
                else:
                    criterion.certified = data["is_certified"]
                    criterion.certified_at = timezone.now()
                    criterion.data_returned_by_api = data["raw_response"]
                    criterion.certification_period = None
                    start_at, end_at = data["start_at"], data["end_at"]
                    if start_at and end_at:
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


@task(takes_context=True)
def async_certify_criteria(model_name, eligibility_diagnosis_pk, *, task=None):
    model = apps.get_model("eligibility", model_name)
    eligibility_diagnosis = model.objects.select_related("job_seeker__jobseeker_profile").get(
        pk=eligibility_diagnosis_pk
    )
    try:
        certify_criteria(eligibility_diagnosis)
    except RetryTask:
        if not task or task.retries < 100:
            raise
        logger.exception("Retry limit reached for ‘%s’ PK ‘%d’, bailing out.", model_name, eligibility_diagnosis_pk)
