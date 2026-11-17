import logging

from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import on_commit_task

from itou.users.enums import Title
from itou.users.models import CNAVRecord
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
        "number": input_data["nir"],
        "name": input_data["last_name"],  # Update to birth_name if available
        "birth_date": input_data["birthdate"],
    }
    if "title" in input_data:
        payload["sex_code"] = {Title.M: 1, Title.MME: 2}[input_data["title"]]
    if "first_name" in input_data:
        payload["first_names"] = input_data["first_name"]
    return payload


def retrieve_cnav_infos(record_pk):
    cnav_record = (
        CNAVRecord.objects.select_related("profile__user")
        .select_for_update(of=("self",), nokey=True)
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
        try:
            interops_result = client.identity(**payload)
        except Exception:
            # TODO: handle 429 error
            cnav_record.save(update_fields={"last_attempt_at"})
        else:
            cnav_record.result = interops_result.asdict()
            cnav_record.save(update_fields={"result", "last_attempt_at"})


@on_commit_task(context=True)  # Retry once a day during 90 days.
def plan_retrieve_cnav_infos(*, record_pk):
    with transaction.atomic():
        retrieve_cnav_infos(record_pk)
