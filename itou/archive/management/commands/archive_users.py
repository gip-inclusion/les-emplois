import logging

from django.db import transaction
from sentry_sdk.crons import monitor

from itou.archive.models import ArchivedJobSeekerProfile, ArchivedUser
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
            help="Archive users",
        )

        parser.add_argument(
            "--size",
            action="store_true",
            help="batch size to process",
        )

    @monitor(monitor_slug="archive_users")
    def handle(self, *args, **options):
        self.wet_run = options["wet_run"]
        self.batch_size = options["size"] if options["size"] else BATCH_SIZE

        self.logger.info("Archiving users, %s mode", "wet_run" if self.wet_run else "dry_run")

        archived_users = []
        archived_jobseekers = []

        with transaction.atomic():
            for user in (users := User.objects.filtre(kind=UserKind.JOB_SEEKER, is_active=False)[: self.batch_size]):
                archived_user = ArchivedUser(
                    date_joined=user.date_joined,
                    first_login=user.first_login,
                    last_login=user.last_login,
                    archived_at=user.archived_at,
                    user_signup_kind=user.created_by.kind,
                    department=user.department,
                    title=user.title,
                    identity_provider=user.identity_provider,
                    kind=user.kind,
                )
                archived_users.append(archived_user)

                # TBC with jobseeker profile

            if self.wet_run:
                ArchivedUser.objects.bulk_create(archived_users)
            self.logger.info("Archived users, count: %d", len(archived_users))
