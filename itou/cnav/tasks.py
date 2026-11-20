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


def _record_to_payload(cnav_record: CNAVRecord):
    payload = {
        "number": cnav_record.input_nir[:13],
        "name": cnav_record.input_last_name,  # Update to birth_name if available
    }
    if cnav_record.input_first_name:
        payload["first_names"] = cnav_record.input_first_name
    if cnav_record.input_title:
        payload["sex_code"] = {Title.M: 1, Title.MME: 2}[cnav_record.input_title]
    if cnav_record.input_birthdate:
        payload["birth_date"] = cnav_record.input_birthdate
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

    payload = _record_to_payload(cnav_record)

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
                print(exc.response.json())
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
