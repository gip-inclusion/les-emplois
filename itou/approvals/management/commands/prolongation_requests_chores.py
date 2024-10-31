from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import F, Q
from django.template.defaultfilters import pluralize
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.approvals.notifications import ProlongationRequestCreatedReminderForPrescriberNotification
from itou.prescribers.models import PrescriberMembership
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("command", choices=["email_reminder"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @transaction.atomic
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
                ProlongationRequestCreatedReminderForPrescriberNotification(
                    prolongation_request.validated_by,
                    prolongation_request.prescriber_organization,
                    prolongation_request=prolongation_request,
                ).send()
                colleagues_to_notify = [
                    membership.user
                    for membership in PrescriberMembership.objects.active()
                    .filter(organization=prolongation_request.prescriber_organization)
                    .exclude(user=prolongation_request.validated_by)
                    .select_related("user")
                    # Limit to the last 10 active colleagues, admins take precedence over regular members.
                    # It should cover the ones dedicated to the IAE and some more.
                    .order_by("-is_admin", F("user__last_login").desc(nulls_last=True), "-joined_at", "-pk")[:10]
                ]
                for colleague in colleagues_to_notify:
                    ProlongationRequestCreatedReminderForPrescriberNotification(
                        colleague,
                        prolongation_request.prescriber_organization,
                        prolongation_request=prolongation_request,
                    ).send()

                prolongation_request.reminder_sent_at = timezone.now()
                prolongation_request.save(update_fields=["reminder_sent_at"])
                prolongation_reminded += 1
        self.stdout.write(
            f"{prolongation_reminded}/{len(queryset)} prolongation request{pluralize(queryset)} reminded"
        )

    def handle(self, *, command, wet_run, **options):
        if command == "email_reminder":
            self.send_reminder_to_prescriber_organization_other_members(wet_run=wet_run)
