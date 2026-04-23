from django.db.models import F, Q
from itoutils.django.commands import dry_runnable

from itou.companies import models
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = """Update the company job_app_score"""

    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        nb_updated = (
            models.Company.objects.with_computed_job_app_score()
            .exclude(Q(job_app_score=F("computed_job_app_score")))
            .update(job_app_score=F("computed_job_app_score"))
        )
        self.logger.info("Updated %d companies", nb_updated)
