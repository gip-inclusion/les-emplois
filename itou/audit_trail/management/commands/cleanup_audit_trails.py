from django.template.defaultfilters import pluralize

from itou.audit_trail.models import AuditTrail
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Cleanup audit trails."

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, *args, **kwargs):
        count, _ = AuditTrail.objects.cleanup()
        self.logger.info(f"Deleted {count} old {AuditTrail.__name__}{pluralize(count)}")
