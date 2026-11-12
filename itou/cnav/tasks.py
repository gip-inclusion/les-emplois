import logging

from django.utils import timezone

from itou.users.enums import Title
from itou.users.models import CNAVRecord
from itou.utils.apis.cnav import get_client


logger = logging.getLogger(__name__)

ALLOWED_RETRIEVAL_FIELDS = [
    # User model
    "title",
    "last_name",
    "first_name",
    # JobSeekerProfile model
    "birthdate",
    "nir",
]


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
    if cnav_record.input_data:
        retrieval_fields = set(cnav_record.input_data)
        assert retrieval_fields <= set(ALLOWED_RETRIEVAL_FIELDS), retrieval_fields
        if isinstance(cnav_record.input_data, dict):
            payload = {
                "number": cnav_record.input_data["nir"],
                "name": cnav_record.input_data["last_name"],  # Update to birth_name if available
                "birth_date": cnav_record.input_data["birthdate"],
            }
            if "title" in retrieval_fields:
                payload["sex_code"] = {Title.M: 1, Title.MME: 2}[cnav_record.input_data["title"]]
            if "first_name" in retrieval_fields:
                payload["first_names"] = cnav_record.input_data["first_name"]
        else:
            assert isinstance(cnav_record.input_data, list), type(cnav_record.input_data)
            assert cnav_record.profile

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
