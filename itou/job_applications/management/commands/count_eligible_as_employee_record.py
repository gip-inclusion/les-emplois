from django.core.management.base import BaseCommand

from itou.companies.models import Company
from itou.job_applications.models import JobApplication


DEAD_SIRET = {"40089251900005"}


class Command(BaseCommand):
    def handle(self, **options):
        siaes = (
            Company.objects.filter(kind__in=Company.ASP_EMPLOYEE_RECORD_KINDS, convention__isnull=False)
            .order_by("siret", "kind")
            .iterator()
        )
        for siae in siaes:
            if siae.siret in DEAD_SIRET:
                continue
            end_count = JobApplication.objects.eligible_as_employee_record(siae).count()
            print(f"SIAE {siae.siret} ({siae.kind}): {end_count}")
