import logging

from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.status import models, probes
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run status probes"

    @monitor(
        monitor_slug="run-status-probes",
        monitor_config={
            "schedule": {"type": "crontab", "value": "*/5 * * * *"},
            "checkin_margin": 2,
            "max_runtime": 5,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, **options):
        self.logger.info("Start probing")

        probes_classes = probes.get_probes_classes()
        self._check_and_remove_dangling_probes(probes_classes)
        self._run_probes(probes_classes)

        self.logger.info("Finished probing")

    def _run_probes(self, probes_classes):
        self.logger.info("Running probes - count=%s", len(probes_classes))

        for probe in probes_classes:
            try:
                success, info = probe().check()
            except Exception as e:
                logger.exception("Probe %r failed", probe.name)
                success, info = False, str(e)
            else:
                logger.info("Probe %r succeeded", probe.name)

            status, _ = models.ProbeStatus.objects.get_or_create(name=probe.name)
            if success:
                status.last_success_at = timezone.now()
                status.last_success_info = info
            else:
                status.last_failure_at = timezone.now()
                status.last_failure_info = info
            status.save()

    def _check_and_remove_dangling_probes(self, current_probes):
        self.logger.info("Checking dangling probes")

        names_in_database = set(models.ProbeStatus.objects.values_list("name", flat=True))
        names_in_code = {probe.name for probe in current_probes}

        dangling_names = set(sorted(names_in_database - names_in_code))
        if dangling_names:
            self.logger.info("Removing dangling probes: %s", dangling_names)
            models.ProbeStatus.objects.filter(name__in=dangling_names).delete()
        else:
            self.logger.info("No dangling probes found")
