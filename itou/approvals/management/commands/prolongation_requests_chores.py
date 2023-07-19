from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand
from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.approvals.notifications import ProlongationRequestCreatedReminder


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("command", choices=["auto_grant", "email_reminder"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def grant_older_pending_requests(self, wet_run):
        queryset = ProlongationRequest.objects.filter(
            status=ProlongationRequestStatus.PENDING,
            created_at__date__lt=timezone.localdate() - relativedelta(days=30),
        ).select_related("approval", "approval__user", "declared_by_siae", "validated_by", "prescriber_organization")
        self.stdout.write(f"{len(queryset)} prolongation request{pluralize(queryset)} can be automatically granted")

        prolongation_created = 0
        for prolongation_request in queryset:
            if wet_run:
                prolongation_request.grant(prolongation_request.validated_by)
                prolongation_created += 1
        self.stdout.write(
            f"{prolongation_created}/{len(queryset)} prolongation request{pluralize(queryset)} automatically granted"
        )

    def send_reminder_to_prescriber_organization_other_members(self, wet_run):
        queryset = ProlongationRequest.objects.filter(
            status=ProlongationRequestStatus.PENDING,
            created_at__date__lte=timezone.localdate() - relativedelta(days=7),
            reminder_sent_at=None,
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
        if command == "auto_grant":
            self.grant_older_pending_requests(wet_run=wet_run)
        elif command == "email_reminder":
            self.send_reminder_to_prescriber_organization_other_members(wet_run=wet_run)
