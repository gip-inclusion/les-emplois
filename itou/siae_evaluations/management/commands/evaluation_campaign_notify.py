import datetime

from dateutil.relativedelta import relativedelta
from django.db.models import Exists, F, Max, OuterRef, Q
from django.utils import timezone

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.emails import CampaignEmailFactory, SIAEEmailFactory
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria, EvaluatedSiae, EvaluationCampaign
from itou.utils.command import BaseCommand
from itou.utils.emails import send_email_messages


class Command(BaseCommand):
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

        # When SIAE submissions are frozen, notify institutions:
        # - on the day submissions are frozen, and
        # - 7 days after submissions have been frozen.
        siae_subq = EvaluatedSiae.objects.filter(evaluation_campaign_id=OuterRef("pk"))
        submissions_frozen = ~Exists(siae_subq.filter(submission_freezed_at=None))
        has_siae_to_control = Exists(
            siae_subq.filter(
                Exists(
                    EvaluatedAdministrativeCriteria.objects.filter(
                        evaluated_job_application__evaluated_siae=OuterRef("pk"),
                        review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
                        submitted_at__isnull=False,
                    )
                ),
            ).filter(
                Q(reviewed_at=None, evaluation_campaign__calendar__adversarial_stage_start__gt=today)
                | Q(final_reviewed_at=None, evaluation_campaign__calendar__adversarial_stage_start__lte=today)
            )
        )
        for campaign in campaigns.filter(
            Q(submission_freeze_notified_at=None)
            | Q(submission_freeze_notified_at__date__lte=today - relativedelta(days=7)),
            submissions_frozen,
            has_siae_to_control,
        ):
            action = None
            if campaign.submission_freeze_notified_at is None:
                send_email_messages([CampaignEmailFactory(campaign).submission_frozen()])
                action = "Instructed"
            else:
                submission_frozen_at = EvaluatedSiae.objects.filter(evaluation_campaign=campaign).aggregate(
                    Max("submission_freezed_at")
                )["submission_freezed_at__max"]
                if submission_frozen_at - campaign.submission_freeze_notified_at <= datetime.timedelta(days=7):
                    send_email_messages([CampaignEmailFactory(campaign).submission_frozen_reminder()])
                    action = "Reminded"
            if action:
                self.stdout.write(f"{action} “{campaign.institution}” to control SIAE during the submission freeze.")
                campaign.submission_freeze_notified_at = timezone.now()
                campaign.save(update_fields=["submission_freeze_notified_at"])
