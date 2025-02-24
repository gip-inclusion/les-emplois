import httpx
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from huey.contrib.djhuey import task

from itou.users.enums import UserKind
from itou.utils.urls import get_absolute_url


@task(retries=3, retry_delay=10)
def add_records(doc_id, table_id, records):
    if settings.GRIST_API_KEY is None:
        return
    url = f"https://grist.numerique.gouv.fr/api/docs/{doc_id}/tables/{table_id}/records"
    response = httpx.post(
        url,
        headers={"Authorization": "Bearer " + settings.GRIST_API_KEY},
        json={"records": records},
    )
    return response.raise_for_status().json()


def get_user_admin_url(user):
    return get_absolute_url(reverse("admin:users_user_change", args=(user.pk,)))


def get_user_kind_display(user):
    if user.kind == UserKind.EMPLOYER:
        return "employeur"
    elif user.kind == UserKind.PRESCRIBER:
        if user.is_prescriber_with_authorized_org:
            return "prescripteur habilité"
        return "orienteur"
    raise ValueError("Invalid user kind: %s", user.kind)


def log_contact_info_display(current_user, follow_up_group, target_participant, mode):
    doc_id = "6tLJYftGnEBTg5yfTCs5N5"
    table_id = "Intentions_mer"

    referent_mapping = dict(follow_up_group.memberships.values_list("member_id", "is_referent"))

    new_record = {
        "fields": {
            "timestamp": int(timezone.now().timestamp()),
            "current_user_id": current_user.pk,
            "current_beneficiary_id": follow_up_group.beneficiary.pk,
            "target_participant_id": target_participant.pk,
            "contact_mode": mode,
            "current_user_name": current_user.get_full_name(),
            "current_user_email": current_user.email,
            "current_user_type": get_user_kind_display(current_user),
            "current_user_is_referent": referent_mapping[current_user.pk],
            "current_user_admin_url": get_user_admin_url(current_user),
            "beneficiary_name": follow_up_group.beneficiary.get_full_name(),
            "beneficiary_admin_url": get_user_admin_url(follow_up_group.beneficiary),
            "target_participant_name": target_participant.get_full_name(),
            "target_participant_email": target_participant.email,
            "target_participant_type": get_user_kind_display(target_participant),
            "target_participant_is_referent": referent_mapping[target_participant.pk],
            "target_participant_admin_url": get_user_admin_url(target_participant),
        }
    }
    add_records(doc_id, table_id, [new_record])
