import datetime
import logging
from json import JSONDecodeError

import httpx
from django.apps import apps
from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import task
from huey.exceptions import RetryTask

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
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
            administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
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
                        case 429:
                            # https://particulier.api.gouv.fr/developpeurs#respecter-la-volumétrie
                            raise RetryTask(delay=int(exc.response.headers["Retry-After"])) from exc
                        case 503:
                            # TODO: Use the error code instead the message when switching to API v3.
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


@task(retries=24 * 6, retry_delay=10 * 60)  # Retry every 10 minutes for 24h.
def async_certify_criteria(model_name, eligibility_diagnosis_pk):
    model = apps.get_model("eligibility", model_name)
    eligibility_diagnosis = model.objects.select_related("job_seeker__jobseeker_profile").get(
        pk=eligibility_diagnosis_pk
    )
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
