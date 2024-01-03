import logging
import os

from django.conf import settings

from itou.utils.export import generate_excel_sheet


class DeprecatedLoggerMixin:
    """
    A mixin used to inject deprecated logger stuff in some of our old management commands.

    Do *not* use it for new commands! Use directly `self.stdout.write()` instead.
    """

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        self.logger.setLevel(logging.INFO)
        if verbosity is not None and verbosity >= 1:
            self.logger.setLevel(logging.DEBUG)


class XlsxExportMixin:
    """
    A mixin with xslx export shortcup
    """

    def export_to_xlsx(self, filename, headers, data):
        path = f"{settings.EXPORT_DIR}/{filename}"
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        with open(path, "wb") as xlsxfile:
            workbook = generate_excel_sheet(headers, data)
            workbook.save(xlsxfile)
        self.stdout.write(f"XLSX file created `{path}`")
