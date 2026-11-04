from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.users.models import User
from itou.utils.command import BaseCommand


# FIXME (dbaty, 2026-09-01): remove this script once users can request
# a 2FA reset on their own.
class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int)
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, user_id, **options):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            print(f"ERROR: user {user_id} cannot be found.")
            return

        updated = ItouTOTPDevice.objects.active().filter(user=user).update(disabled_at=timezone.now())
        if not updated:
            print(f"ERROR: User {user_id} had no active 2FA device. Double-check user id.")
            return
        ItouStaticDevice.objects.filter(user=user).delete()
        self.logger.info("Disabled 2FA device and deleted recovery code for user %s", user.pk)
