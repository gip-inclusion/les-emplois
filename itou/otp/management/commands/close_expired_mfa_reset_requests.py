from django.template.defaultfilters import pluralize

from itou.otp.models import ResetRequest
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Cleanup expired 2fa reset requests."

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, *args, **kwargs):
        count = ResetRequest.objects.close_expired_requests()
        self.logger.info(f"Closed {count} old {ResetRequest.__name__}{pluralize(count)}")
