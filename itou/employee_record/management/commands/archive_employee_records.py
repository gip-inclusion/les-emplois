from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand, dry_runnable


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        self.logger.info("Start archiving employee records")

        archivable = (
            EmployeeRecord.objects.archivable()
            .order_by("job_application__approval__end_at")
            .select_related("job_application__approval")
        )
        self.logger.info(f"Found {len(archivable)} archivable employee record(s)")

        archived_employee_records = []
        for employee_record in archivable:
            self.logger.info(f"Archiving {employee_record.pk=}")
            try:
                employee_record.archive()
            except Exception as ex:
                self.logger.warning("Can't archive employee_record=%d ex=%s", employee_record.pk, ex)
            else:
                archived_employee_records.append(employee_record)

        self.logger.info("%d/%d employee record(s) were archived", len(archived_employee_records), len(archivable))
