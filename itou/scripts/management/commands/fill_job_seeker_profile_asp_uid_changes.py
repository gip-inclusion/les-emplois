import contextlib

import pgtrigger
from django.db import transaction
from django.utils.crypto import salted_hmac

from itou.users.models import JobSeekerProfile
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--old-secret", dest="old_secret", required=True, type=str)
        parser.add_argument("--new-secret", dest="new_secret", required=True, type=str)
        parser.add_argument(
            "--old-secret-last-pk",
            dest="old_secret_last_pk",
            required=True,
            type=int,
            help="Use a high value (99999999) and a dry run to find it",
        )
        parser.add_argument("--start-pk", dest="start_pk", type=int, default=0)
        parser.add_argument("--wet-run", dest="wet_run", action="store_true", default=False)

    def handle(self, *, old_secret, new_secret, old_secret_last_pk, start_pk, wet_run, **options):
        has_data_changed_fields = {"birthdate", "nir"}  # Required by `JobSeekerProfile.save()` not the script
        for profile in (
            JobSeekerProfile.objects.filter(pk__gte=start_pk)
            .order_by("pk")
            .only("pk", "user_id", "asp_uid", "fields_history", *has_data_changed_fields)
            .iterator()
        ):
            print(f"Check {profile.pk=}")
            old_uid = salted_hmac(key_salt="job_seeker.id", value=profile.user_id, secret=old_secret).hexdigest()[:30]
            new_uid = salted_hmac(key_salt="job_seeker.id", value=profile.user_id, secret=new_secret).hexdigest()[:30]
            expected_uid, uid_generation = (
                (old_uid, "old_secret_uid") if profile.pk <= old_secret_last_pk else (new_uid, "new_secret_uid")
            )
            if profile.asp_uid == expected_uid:  # Everything is fine, moving on
                print(f"> Found expected {uid_generation=} {profile.asp_uid=}")
                continue

            # Prevent duplication, shouldn't be necessary when adding fields_history but the script will take
            # some time so better handling that case from the start, especially if we want to re-run it.
            already_logged = False
            for changes in profile.fields_history:
                with contextlib.suppress(KeyError):
                    already_logged |= (
                        changes["after"]["asp_uid"] == profile.asp_uid and changes["before"]["asp_uid"] == expected_uid
                    )
            if already_logged:
                print(f"> Change to {profile.asp_uid=} was already logged")
                continue

            print(f"> Found an unlogged change: {profile.asp_uid=} {old_uid=} {new_uid=}")
            if wet_run:
                profile.fields_history.append(
                    {
                        "before": {"asp_uid": expected_uid},
                        "after": {"asp_uid": profile.asp_uid},
                        "_timestamp": "",
                    }
                )
                with (
                    transaction.atomic(),
                    pgtrigger.ignore("users.JobSeekerProfile:job_seeker_profile_fields_history"),
                ):
                    profile.save(update_fields={"fields_history"})
