from django.core.management.base import BaseCommand

from itou.employee_record import constants
from itou.employee_record.models import EmployeeRecord


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    def handle(self, wet_run=False, **options):
        """
        Archive old employee record data:
        records are not deleted but their `archived_json` field is erased if employee record has been
        in `PROCESSED` status for more than EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS days
        """
        self.stdout.write(
            f"Archiving employee records (more than {constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS} days old)"
        )
        archivable = EmployeeRecord.objects.archivable()

        if (cnt := archivable.count()) > 0:
            self.stdout.write(f"Found {cnt} archivable employee record(s)")
            if not wet_run:
                return
            archived_cnt = 0

            # A bulk update will increase performance if there are a lot of employee records to update.
            # However, if there is no performance issue, it is preferable to keep the archiving
            # and validation logic in the model (update_as_archived).
            # Update: let's bulk, with a batch size of 100 records
            for er in archivable:
                try:
                    # Do not trigger a save() call on the object
                    er.update_as_archived(save=False)
                    archived_cnt += 1
                except Exception as ex:
                    self.stdout.write(f"Can't archive record {er=} {ex=}")

            # Bulk update (100 records block):
            EmployeeRecord.objects.bulk_update(archivable, ["status", "updated_at", "archived_json"], batch_size=100)

            self.stdout.write(f"Archived {archived_cnt}/{cnt} employee record(s)")
        else:
            self.stdout.write("No archivable employee record found, exiting.")
