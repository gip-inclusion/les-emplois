import time

from django.core.management.base import BaseCommand
from django.db.models import F, Q

from itou.companies import models


class Command(BaseCommand):
    help = """Update the company job_app_score"""

    def handle(self, **options):
        start = time.perf_counter()
        nb_updated = (
            models.Company.objects.with_computed_job_app_score()
            # Do not update if nothing changes (NULL values have to be handled separately because NULL)
            .exclude(
                Q(job_app_score=F("computed_job_app_score"))
                | Q(job_app_score__isnull=True) & Q(computed_job_app_score__isnull=True)
            ).update(job_app_score=F("computed_job_app_score"))
        )
        self.stdout.write(f"Updated {nb_updated} companies in {time.perf_counter() - start:.3f} seconds")
