import time

from django.core.management.base import BaseCommand
from django.db import connection

from itou.approvals.models import Suspension
from itou.job_applications.models import JobApplication


class Command(BaseCommand):
    def handle(self, **options):
        for model in [Suspension, JobApplication]:
            objects_to_migrate = model.objects.filter(updated_at=None)
            print(f"{model} before: {objects_to_migrate.count()}")

            with connection.cursor() as cursor:
                mod_for_batch_size = objects_to_migrate.count() // 1000
                for cpt in range(mod_for_batch_size):
                    cursor.execute(
                        """
                        UPDATE approvals_suspension
                        SET updated_at = created_at
                        WHERE updated_at IS NULL
                        AND id %% %s = %s""",
                        [mod_for_batch_size, cpt],
                    )
                    print(f"{model} left: {objects_to_migrate.count()}")
                    time.sleep(1)

            print(f"{model} after: {objects_to_migrate.count()}")
