import logging

from django.db import transaction
from sentry_sdk.crons import monitor

from itou.archive.models import ArchivedJobSeeker
from itou.users.models import User, UserKind
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)

BATCH_SIZE = 100


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the actual archiving of jobseekers",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of jobseekers to process in a batch",
        )

    def anonymized_jobseeker(self, user):
        kwargs = {
            "date_joined": user.date_joined.date(),
            "first_login": user.first_login.date() if user.first_login else None,
            "last_login": user.last_login.date() if user.last_login else None,
            "user_signup_kind": getattr(user.created_by, "kind", None),
            "department": user.department,
            "title": user.title,
            "identity_provider": user.identity_provider,
            "kind": user.kind,
        }

        if hasattr(user, "jobseeker_profile"):
            profile = user.jobseeker_profile
            kwargs.update(
                {
                    "had_pole_emploi_id": bool(profile.pole_emploi_id),
                    "had_nir": bool(profile.nir),
                    "lack_of_nir_reason": profile.lack_of_nir_reason,
                    "nir_sex": profile.nir[0] if user.jobseeker_profile.nir else None,
                    "nir_year": profile.nir[1:3] if user.jobseeker_profile.nir else None,
                    "birth_year": profile.birthdate.year if profile.birthdate else None,
                }
            )

        return ArchivedJobSeeker(**kwargs)

    @monitor(monitor_slug="archive_jobseekers")
    def handle(self, *args, wet_run, batch_size, **options):
        self.logger.info("Starting jobseeker archiving in %s mode", "wet_run" if wet_run else "dry_run")

        users_to_archive = User.objects.filter(
            kind=UserKind.JOB_SEEKER, is_active=False, upcoming_deletion_notified_at__isnull=False
        )[:batch_size]
        archived_jobseekers = [self.anonymized_jobseeker(user) for user in users_to_archive]

        if wet_run:
            with transaction.atomic():
                ArchivedJobSeeker.objects.bulk_create(archived_jobseekers)
                User.objects.filter(id__in=[user.id for user in users_to_archive]).delete()

        self.logger.info("Archived jobseekers, count: %d", len(archived_jobseekers))
