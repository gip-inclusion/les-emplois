from itoutils.django.commands import dry_runnable

from itou.employee_record.models import EmployeeRecord
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument("--wet-run", action="store_true")

    @dry_runnable
    def handle(self, **options):
        self.logger.info("Start archiving employee records")

        archivable = (
            EmployeeRecord.objects.possibly_archivable()
            .order_by("job_application__approval__end_at")
            .select_related("job_application__approval")
        )
        self.logger.info(f"Found {len(archivable)} possibly archivable employee record(s)")

        archived_nb = 0
        for employee_record in archivable:
            try:
                employee_record.archive()
            except Exception as ex:
                self.logger.warning("Can't archive employee_record=%d ex=%s", employee_record.pk, ex)
            else:
                archived_nb += 1

        self.logger.info("%d/%d employee record(s) were archived", archived_nb, len(archivable))
