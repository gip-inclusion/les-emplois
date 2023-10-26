from itou.approvals.export import export_approvals
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Export all valid approvals (PASS IAE, not Pole emploi) to an Excel file.

    This file is:
    * named 'export_pass_iae_MMDDYYY_HHMINSEC.xlsx' (datetime of export)
    * put in the 'exports' folder

    There is no optional argument at the moment.
    """

    help = "Export the content of the Approvals from the database into an xlsx file."

    def handle(self, **options):
        self.stdout.write("Exporting approvals / PASS IAE")
        result = export_approvals()
        self.stdout.write("Approvals / PASS IAE export file written to:")
        self.stdout.write(result)
