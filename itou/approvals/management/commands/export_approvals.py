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

    help = "Export the content of the Approvals from the database into an xlsx file."

    def handle(self, **options):
        self.stdout.write("Exporting approvals")

        result = export_approvals()

        self.stdout.write("Done!")
        self.stdout.write(f"Approvals / PASS IAE export file written to: '{result}'")
