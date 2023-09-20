import time

from django.core.management.base import BaseCommand

from itou.asp.models import SiaeKind
from itou.employee_record.models import EmployeeRecord


BATCH_SIZE = 2000


class Command(BaseCommand):
    def handle(self, **options):
        objects_to_migrate = (
            EmployeeRecord.objects.filter(asp_measure=None)
            .select_related("job_application__to_siae")
            .only("job_application__to_siae__kind")
        )
        total_objects = objects_to_migrate.count()
        print(f"Before: {total_objects}")

        batch = []
        for er in objects_to_migrate.iterator():
            er.asp_measure = SiaeKind.from_siae_kind(er.job_application.to_siae.kind)
            batch.append(er)
            if len(batch) >= min(BATCH_SIZE, total_objects):
                EmployeeRecord.objects.bulk_update(batch, fields=["asp_measure"])
                batch = []
                print(f"Remaining: {objects_to_migrate.count()}")
                time.sleep(1)

        print(f"After: {objects_to_migrate.count()}")
