import logging

from django.utils import timezone
from sentry_sdk.crons import monitor
from tqdm import tqdm

from itou.status import models, probes
from itou.utils.command import BaseCommand


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run status probes"

    @monitor(monitor_slug="run-status-probes")
    def handle(self, **options):
        self.stdout.write("Start probing")

        probes_classes = probes.get_probes_classes()
        self._check_and_remove_dangling_probes(probes_classes)
        self._run_probes(probes_classes)

        self.stdout.write("Finished probing")

    def _run_probes(self, probes_classes):
        self.stdout.write("Running probes")

        progress_bar = tqdm(total=len(probes_classes), file=self.stderr)
        for probe in probes_classes:
            try:
                success, info = probe().check()
            except Exception as e:
                logger.exception("Probe %r failed", probe.name)
                success, info = False, str(e)

            status, _ = models.ProbeStatus.objects.get_or_create(name=probe.name)
            if success:
                status.last_success_at = timezone.now()
                status.last_success_info = info
            else:
                status.last_failure_at = timezone.now()
                status.last_failure_info = info
            status.save()
            progress_bar.update(1)
        progress_bar.close()

    def _check_and_remove_dangling_probes(self, current_probes):
        self.stdout.write("Check dangling probes")

        names_in_database = set(models.ProbeStatus.objects.values_list("name", flat=True))
        names_in_code = {probe.name for probe in current_probes}

        dangling_names = set(sorted(names_in_database - names_in_code))
        if dangling_names:
            self.stdout.write(f"Removing dangling probes: {dangling_names}")
            models.ProbeStatus.objects.filter(name__in=dangling_names).delete()
        else:
            self.stdout.write("No dangling probes found")
