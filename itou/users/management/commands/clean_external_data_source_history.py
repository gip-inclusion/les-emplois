import math
from itertools import batched

from itou.users.models import User
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Remove kind field from external_data_source_history : we never changed the user kind whan logging with an SSO.
    Also clean is_siae_staff/is_prescriber/is_job_seeker the fields used before adding User.kind.
    """

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, *args, **options):
        user_ids = list(User.objects.exclude(external_data_source_history=None).values_list("id", flat=True))

        nb_chunks = math.ceil(len(user_ids) / 1000)
        count = 1

        for batch_ids in batched(user_ids, 1000):
            print(f"{count}/{nb_chunks}")
            users = User.objects.filter(id__in=batch_ids)
            for user in users:
                new_history = []
                previous_update = {}
                for update in user.external_data_source_history:
                    if update["field_name"] in [
                        "kind",
                        "is_siae_staff",
                        "is_prescriber",
                        "is_job_seeker",
                        "is_pe_jobseeker",
                    ]:
                        # No need to track changes in kind or the previously used fields since we never applied them
                        continue
                    if previous_update.get(update["field_name"]) == update["value"]:
                        # No update here, it's the same value
                        continue
                    if (
                        update["field_name"] in ["first_name", "last_name"]
                        and previous_update.get(update["field_name"], "").lower() == update["value"].lower()
                    ):
                        # Only the case changed, don't track it
                        continue
                    new_history.append(update)
                    previous_update[update["field_name"]] = update.get("value")
                user.external_data_source_history = new_history

            User.objects.bulk_update(users, fields=["external_data_source_history"])
            count += 1
