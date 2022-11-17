from dateutil.relativedelta import relativedelta
from django.core.management import BaseCommand
from django.utils import timezone

from itou.siae_evaluations.models import EvaluationCampaign
from itou.utils.emails import send_email_messages


class Command(BaseCommand):
    def handle(self, **options):
        today = timezone.localdate()
        for campaign in EvaluationCampaign.objects.filter(
            evaluations_asked_at__date__lte=today - relativedelta(days=30),
            ended_at=None,
        ).select_related("institution"):
            emails = []
            evaluated_siaes = (
                campaign.evaluated_siaes.did_not_send_proof()
                .filter(reviewed_at=None, reminder_sent_at=None)
                .select_related("evaluation_campaign__institution", "siae__convention")
            )
            for evaluated_siae in evaluated_siaes:
                emails.append(evaluated_siae.get_email_to_siae_notify_before_adversarial_stage())
            if emails:
                send_email_messages(emails)
                evaluated_siaes.update(reminder_sent_at=timezone.now())
                self.stdout.write(
                    f"Emailed reminders to {len(emails)} SIAE which did not submit proofs to {campaign}."
                )
