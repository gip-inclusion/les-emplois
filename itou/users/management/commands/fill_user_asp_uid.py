from django.core.management.base import BaseCommand

from itou.users.models import User


BATCH_SIZE = 5000


class Command(BaseCommand):
    def handle(self, **options):
        to_update = []

        for user in User.objects.filter(is_job_seeker=True, asp_uid=None).only("pk").iterator(BATCH_SIZE):
            user.asp_uid = user.jobseeker_hash_id
            to_update.append(user)

            if len(to_update) >= BATCH_SIZE:
                User.objects.bulk_update(to_update, ["asp_uid"], batch_size=BATCH_SIZE)
                to_update = []

        User.objects.bulk_update(to_update, ["asp_uid"], batch_size=BATCH_SIZE)
