from django.db.models import F, Q

from itou.companies import models
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = """Update the company job_app_score"""

    def handle(self, **options):
        nb_updated = (
            models.Company.objects.with_computed_job_app_score()
            .exclude(Q(job_app_score=F("computed_job_app_score")))
            .update(job_app_score=F("computed_job_app_score"))
        )
        self.logger.info("Updated %d companies", nb_updated)
