import dataclasses
import datetime
import logging

import httpx
from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import on_commit_task

from itou.cnav.models import CNAVRecord
from itou.users.enums import Title
from itou.utils.apis.cnav import get_client


logger = logging.getLogger(__name__)

MANDATORY_FIELDS = [
    "birthdate",
    "last_name",
    "nir",
]

ALLOWED_FIELDS = [
    # User model
    "first_name",
    "last_name",
    "title",
    # JobSeekerProfile model
    "birthdate",
    "nir",
]

assert set(MANDATORY_FIELDS) <= set(ALLOWED_FIELDS)


def _input_to_payload(input_data):
    payload = {
        "number": input_data["nir"][:13],
        "name": input_data["last_name"],  # Update to birth_name if available
        "birth_date": datetime.date.fromisoformat(input_data["birthdate"]),
    }
    if "title" in input_data:
        payload["sex_code"] = {Title.M: 1, Title.MME: 2}[input_data["title"]]
    if "first_name" in input_data:
        payload["first_names"] = input_data["first_name"]
    return payload


def retrieve_cnav_infos(record_pk):
    cnav_record = (
        CNAVRecord.objects.select_related("profile__user")
        .select_for_update(of=("self",), no_key=True)
        .filter(pk=record_pk)
        .first()
    )
    if cnav_record is None:
        logger.warning("CNAVRecord pk=%s was deleted - ignoring task", record_pk)
        return
    if cnav_record.result is not None:
        logger.info("CNAVRecord pk=%s has already been processed - ignoring task", record_pk)
        return
    if not cnav_record.input_data or not isinstance(cnav_record.input_data, dict):
        logger.error("Invalid input_data for CNAVRecord pk=%s", record_pk)
        return

    retrieval_fields = set(cnav_record.input_data)
    if not set(MANDATORY_FIELDS) <= retrieval_fields <= set(ALLOWED_FIELDS):
        logger.error("Invalid fields in input_data of CNAVRecord pk=%s : %s", record_pk, retrieval_fields)
        return
    payload = _input_to_payload(cnav_record.input_data)

    with get_client() as client:
        cnav_record.last_attempt_at = timezone.now()
        update_fields = {"last_attempt_at"}
        try:
            interops_result = client.identity(**payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("Hit rate limit while trying to retrieve data for CNAVRecord pk=%s", record_pk)
                try:
                    retry_after = int(exc.response.headers.get("Retry-After", "3600"))
                except ValueError, TypeError:
                    retry_after = 3600
                cnav_record.next_attempt_at = timezone.now() + datetime.timedelta(seconds=retry_after)
                update_fields.add("next_attempt_at")
            else:
                logger.warning(
                    "HTTPStatusError while trying to retrieve data for CNAVRecord pk=%s : %s", record_pk, exc
                )
        except httpx.HTTPError as exc:
            logger.warning("HTTPError while trying to retrieve data for CNAVRecord pk=%s : %s", record_pk, exc)
        except Exception as exc:
            logger.error("Error while trying to retrieve data for CNAVRecord pk=%s : %s", record_pk, exc)
        else:
            cnav_record.result = dataclasses.asdict(interops_result)
            update_fields.add("result")
        finally:
            cnav_record.save(update_fields=update_fields)


@on_commit_task()
def plan_retrieve_cnav_infos(*, record_pk):
    with transaction.atomic():
        retrieve_cnav_infos(record_pk)
