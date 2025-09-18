from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.siae_evaluations.enums import EvaluatedSiaeFinalState
from itou.siae_evaluations.models import ArchivedEvaluatedSiae, EvaluatedJobApplication, EvaluatedSiae
from itou.utils.command import BaseCommand, dry_runnable


DELAY = timedelta(days=60)


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Archive Siae evalutions whose final state is ACCEPTED, once the evaluation campaign is closed",
        )

    @monitor(
        monitor_slug="archive_accepted_evaluated_siae",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    @transaction.atomic
    def handle(self, *args, wet_run, **options):
        evaluated_siaes = list(
            EvaluatedSiae.objects.filter(
                evaluation_campaign__ended_at__lt=timezone.now() - DELAY,
                final_state=EvaluatedSiaeFinalState.ACCEPTED,
            ).annotate(count_evaluated_applications=Count("evaluated_job_applications__id"))
        )

        archived_evaluated_siaes = [
            ArchivedEvaluatedSiae(
                evaluation_campaign=evaluated_siae.evaluation_campaign,
                siae=evaluated_siae.siae,
                reviewed_at=evaluated_siae.reviewed_at,
                final_reviewed_at=evaluated_siae.final_reviewed_at,
                final_state=evaluated_siae.final_state,
                job_applications_count=evaluated_siae.count_evaluated_applications,
            )
            for evaluated_siae in evaluated_siaes
        ]

        ArchivedEvaluatedSiae.objects.bulk_create(archived_evaluated_siaes)
        EvaluatedJobApplication.objects.filter(evaluated_siae__in=evaluated_siaes).delete()
        EvaluatedSiae.objects.filter(id__in=[evaluated_siae.id for evaluated_siae in evaluated_siaes]).delete()

        self.logger.info("Archived evaluated_siae after campaign is closed, count: %d", len(evaluated_siaes))
