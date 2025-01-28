from django.db.models import F, Q

from itou.companies import models
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = """Update the company job_app_score"""

    def handle(self, **options):
        nb_updated = (
            models.Company.objects.with_computed_job_app_score()
            # Do not update if nothing changes (NULL values have to be handled separately because NULL)
            .exclude(Q(job_app_score=F("computed_job_app_score")) & Q(computed_job_app_score__isnull=False))
            .exclude(Q(job_app_score__isnull=True) & Q(computed_job_app_score__isnull=True))
            .update(job_app_score=F("computed_job_app_score"))
        )
        self.logger.info("Updated %d companies", nb_updated)
