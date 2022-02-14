import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from itou.employee_record.models import EmployeeRecord


class Command(BaseCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        handler = logging.StreamHandler(self.stdout)
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def add_arguments(self, parser):
        """
        Command line arguments
        """
        parser.add_argument(
            "--update", action="store_true", help="Update incoherent employee records status to `INCOHERENT`."
        )

    def _info(self):
        """
        Display a quick summary of current coherence situation.
        """
        processed_count = EmployeeRecord.objects.processed().count()
        incoherent_count = EmployeeRecord.objects.incoherent().count()
        found_incoherent = EmployeeRecord.objects.find_incoherent().count()

        self.logger.info("### Processed employee records summary ###")
        self.logger.info(f"- number of `PROCESSED` employee records  : {processed_count}")
        self.logger.info(f"- number of `INCOHERENT` employee records : {incoherent_count}")
        if found_incoherent > 0:
            self.logger.warning(f"- found {found_incoherent} incoherent employee records.")
            if not self.update:
                self.logger.info("Update them as incoherent with `--update` option.")
        else:
            self.logger.info("Did not find any new incoherent employee record. Good job, James!")

    @transaction.atomic
    def _flag_incoherent_employee_records(self):
        """
        Change status of incoherent employee records to `INCOHERENT`.
        """
        found_incoherent = EmployeeRecord.objects.find_incoherent()

        if found_incoherent.count() == 0:
            return

        self.logger.info("### Updating incoherent employee records status ###")

        nb_flagged = found_incoherent.update(status=EmployeeRecord.Status.INCOHERENT)

        self.logger.info(f"Updated {nb_flagged} incoherent employee record(s).")
        self.logger.info("Done!")

    def handle(self, *_, **options):
        self.update = bool(options.get("update"))

        # Always display info
        self._info()

        if self.update:
            self._flag_incoherent_employee_records()
