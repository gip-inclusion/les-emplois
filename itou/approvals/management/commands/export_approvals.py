import logging

from django.core.management.base import BaseCommand

from itou.approvals.export import export_approvals


class Command(BaseCommand):
    """
    Export all valid approvals (PASS IAE, not Pole emploi) to an Excel file.

    This file is:
    * named 'export_pass_iae_MMDDYYY_HHMINSEC.xslx' (datetime of export)
    * put in the 'exports' folder

    There is no optional argument at the moment.
    """

    help = "Export the content of the approvals from the database into a xlsx file or an output stream."

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def handle(self, **options):

        self.set_logger(options.get("verbosity"))
        self.logger.info(f"Exporting approvals")

        result = export_approvals()

        self.logger.info(f"Done!\nApprovals / PASS IAE export file written to: '{result}'")
