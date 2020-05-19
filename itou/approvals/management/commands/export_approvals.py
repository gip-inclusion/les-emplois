import logging

from django.core.management.base import BaseCommand
from itou.utils.exports.export_approvals import export_approvals


class Command(BaseCommand):

    help = "Export the content of the approvals from the database into a xlsx file or an output stream."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            dest="export_format",
            required=False,
            action="store",
            help="Choose between 'stream' and 'file' export type",
        )

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

    def handle(self, export_format, **options):
        chosen_format = export_format or "file"
        self.set_logger(options.get("verbosity"))
        self.logger.info(f"Exporting approvals (export to '{export_format}')")

        result = export_approvals(chosen_format)

        if chosen_format == "stream":
            self.stdout.write(result)
        else:
            self.logger.info(f"Done! Approvals export file written to: '{result}'")
