from django.conf import settings
from django.utils import timezone

from itou.otp.models import ItouTOTPDevice
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete OTP devices that have been disabled long ago (we keep them for a grace period for auditing purposes)."
    )

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        threshold = timezone.now() - settings.OTP_DEVICES_GRACE_PERIOD_BEFORE_DELETION

        devices = ItouTOTPDevice.objects.filter(disabled_at__lt=threshold)
        if wet_run:
            count, _ = devices.delete()
            self.logger.info("%d disabled TOTP devices have been purged", count)
        else:
            self.logger.info("%d disabled TOTP devices would be purged", devices.count())
