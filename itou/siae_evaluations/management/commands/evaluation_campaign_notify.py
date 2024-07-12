from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from itou.siae_evaluations.emails import CampaignEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria, EvaluatedSiae, EvaluationCampaign
from itou.utils.command import BaseCommand
from itou.utils.emails import send_email_messages


class Command(BaseCommand):
    @transaction.atomic
    def handle(self, **options):
        today = timezone.localdate()
        campaigns = EvaluationCampaign.objects.filter(ended_at=None).select_related("institution")
        for campaign in campaigns.filter(
            evaluations_asked_at__date__lte=today - relativedelta(days=30),
            # Don’t send amicable stage notifications past the adversarial stage.
            calendar__adversarial_stage_start__gte=today,
        ):
            emails = []
            evaluated_siaes = (
                campaign.evaluated_siaes.did_not_send_proof()
                .filter(reviewed_at=None, reminder_sent_at=None)
                .select_related(
                    "evaluation_campaign__calendar",
                    "evaluation_campaign__institution",
                    "siae__convention",
                )
            )
            for evaluated_siae in evaluated_siaes:
                emails.append(SIAEEmailFactory(evaluated_siae).notify_before_adversarial_stage())
            if emails:
                send_email_messages(emails)
                evaluated_siaes.update(reminder_sent_at=timezone.now())
                self.stdout.write(
                    f"Emailed first reminders to {len(emails)} SIAE which did not submit proofs to {campaign}."
                )

        for campaign in campaigns.filter(calendar__adversarial_stage_start__lte=today - relativedelta(days=30)):
            emails = []
            evaluated_siaes = (
                campaign.evaluated_siaes.filter(final_reviewed_at=None)
                .exclude(
                    Exists(
                        EvaluatedAdministrativeCriteria.objects.filter(
                            evaluated_job_application__evaluated_siae=OuterRef("pk"),
                            submitted_at__gt=F("evaluated_job_application__evaluated_siae__reviewed_at"),
                        )
                    )
                )
                .filter(Q(reminder_sent_at=None) | Q(reminder_sent_at__lt=F("reviewed_at")))
                .select_related("evaluation_campaign__institution", "siae__convention")
            )
            for evaluated_siae in evaluated_siaes:
                emails.append(SIAEEmailFactory(evaluated_siae).notify_before_campaign_close())
            if emails:
                send_email_messages(emails)
                evaluated_siaes.update(reminder_sent_at=timezone.now())
                self.stdout.write(
                    f"Emailed second reminders to {len(emails)} SIAE which did not submit proofs to {campaign}."
                )

        # When a campaign is frozen, a notification is sent to institutions synchronously
        # Then every 7 days a reminder email is sent if there is still work to do
        has_siae_to_control = Exists(EvaluatedSiae.objects.to_control_in_campaign(campaign_id=OuterRef("pk")))
        for campaign in campaigns.filter(
            has_siae_to_control,
            submission_freeze_notified_at__date__lte=today - relativedelta(days=7),
        ):
            send_email_messages([CampaignEmailFactory(campaign).submission_frozen_reminder()])
            campaign.submission_freeze_notified_at = timezone.now()
            campaign.save(update_fields=["submission_freeze_notified_at"])
            self.stdout.write(f"Reminded “{campaign.institution}” to control SIAE during the submission freeze.")
