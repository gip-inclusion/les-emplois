from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.siae_evaluations.enums import EvaluatedSiaeFinalState
from itou.siae_evaluations.models import EvaluatedJobApplication, EvaluatedSiae
from itou.utils.command import BaseCommand, dry_runnable


DELAY = timedelta(days=60)


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Archive SIAE evaluations whose final state is ACCEPTED, once the evaluation campaign is closed",
        )

    @monitor(
        monitor_slug="archive_accepted_evaluated_siae",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7 * * *"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    def handle(self, *args, wet_run, **options):
        evaluated_siaes_to_archive = list(
            EvaluatedSiae.objects.filter(
                evaluation_campaign__ended_at__date__lt=timezone.localdate() - DELAY,
                final_state=EvaluatedSiaeFinalState.ACCEPTED,
                archive_accepted_job_applications_nb__isnull=True,
            ).annotate(count_evaluated_applications=Count("evaluated_job_applications__id"))
        )
        self.logger.info("Found count=%d EvaluatedSiae to archive", len(evaluated_siaes_to_archive))
        if not evaluated_siaes_to_archive:
            return

        for evaluated_siae in evaluated_siaes_to_archive:
            evaluated_siae.archive_accepted_job_applications_nb = evaluated_siae.count_evaluated_applications
        EvaluatedSiae.objects.bulk_update(evaluated_siaes_to_archive, ["archive_accepted_job_applications_nb"])
        _, objs = EvaluatedJobApplication.objects.filter(evaluated_siae__in=evaluated_siaes_to_archive).delete()
        deleted_job_applications_nb = objs.get("siae_evaluations.EvaluatedJobApplication", 0)
        self.logger.info("Deleted count=%d linked EvaluatedJobApplication", deleted_job_applications_nb)
        self.logger.info(
            "Archived count=%d EvaluatedSiae: %s",
            len(evaluated_siaes_to_archive),
            sorted(siae.pk for siae in evaluated_siaes_to_archive),
        )
