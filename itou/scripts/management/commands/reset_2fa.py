from itoutils.django.commands import dry_runnable

from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.users.models import User
from itou.utils.command import BaseCommand


# FIXME (dbaty, 2026-09-01): remove this script once users can request
# a 2FA reset on their own.
class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, email, **options):
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            print(f"ERROR: {email} cannot be found.")
            return

        deleted, _ = ItouTOTPDevice.objects.filter(user=user).delete()
        if not deleted:
            print(f"ERROR: User {email} has no 2FA device. Double-check email!")
            return
        ItouStaticDevice.objects.filter(user=user).delete()
        self.logger.info("Deleted 2FA device and recovery code for user %s", user.pk)
