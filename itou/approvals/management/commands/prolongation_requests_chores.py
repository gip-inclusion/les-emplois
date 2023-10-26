from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.approvals.notifications import ProlongationRequestCreatedReminder
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("command", choices=["email_reminder"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def send_reminder_to_prescriber_organization_other_members(self, wet_run):
        first_reminder = Q(reminder_sent_at=None, created_at__date__lte=timezone.localdate() - relativedelta(days=10))
        subsequent_reminders = Q(reminder_sent_at__date__lte=timezone.localdate() - relativedelta(days=10))

        queryset = ProlongationRequest.objects.filter(
            first_reminder | subsequent_reminders,
            status=ProlongationRequestStatus.PENDING,
            # Only send reminders in the first 30 days
            created_at__date__gte=timezone.localdate() - relativedelta(days=30),
        )
        self.stdout.write(f"{len(queryset)} prolongation request{pluralize(queryset)} can be reminded")

        prolongation_reminded = 0
        for prolongation_request in queryset:
            if wet_run:
                ProlongationRequestCreatedReminder(prolongation_request).send()
                prolongation_request.reminder_sent_at = timezone.now()
                prolongation_request.save(update_fields=["reminder_sent_at"])
                prolongation_reminded += 1
        self.stdout.write(
            f"{prolongation_reminded}/{len(queryset)} prolongation request{pluralize(queryset)} reminded"
        )

    def handle(self, *, command, wet_run, **options):
        if command == "email_reminder":
            self.send_reminder_to_prescriber_organization_other_members(wet_run=wet_run)
