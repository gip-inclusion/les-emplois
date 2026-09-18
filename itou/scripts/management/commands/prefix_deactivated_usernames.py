from django.db.models import Q

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


DEACTIVATED_FROM_ADMIN = Q(is_active=False, username__startswith="old_", email__endswith="_old")
DEACTIVATED_FROM_COMMAND = Q(
    is_active=False,
    kind=UserKind.PROFESSIONAL,
    email__isnull=True,
    upcoming_deletion_notified_at__isnull=False,
)


class Command(BaseCommand):
    """
    One-shot: rewrite the username of users deactivated before prefixing the username with `old_<pk>_<sub>`.
    """

    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        deactivated_from_admin = User.objects.filter(DEACTIVATED_FROM_ADMIN)
        deactivated_from_command = User.objects.filter(DEACTIVATED_FROM_COMMAND)

        self.logger.info(
            "Deactivated users found: %d from the admin, %d from the anonymization command",
            deactivated_from_admin.count(),
            deactivated_from_command.count(),
        )

        users_to_update = []
        for user in User.objects.filter(DEACTIVATED_FROM_ADMIN | DEACTIVATED_FROM_COMMAND).all():
            if user.username.startswith(f"old_{user.pk}_"):  # Already rewritten
                continue
            user.username = f"old_{user.pk}_{user.username.removeprefix('old_')}"
            users_to_update.append(user)

        if wet_run:
            nb_updated = User.objects.bulk_update(users_to_update, ["username"])
            self.logger.info("Updated users count=%d", nb_updated)
