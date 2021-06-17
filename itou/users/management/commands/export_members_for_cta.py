import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    """
    Generate a file for "Comités Technique d'Animation"
    listing employers and prescribers belonging to an organization.
    """

    help = "Export employers and prescribers with org for CTA"

    def handle(self, **options):
        sql_query = """
            
        """

        results = self._raw_query_to_dict(sql_query)
        self._write_to_csv(filename="cta_export.csv", results=results)

    def _raw_query_to_dict(self, query):
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _write_to_csv(self, filename, results):
        filepath = os.path.join(settings.EXPORT_DIR, filename)

        # Write CSV
        with open(filepath, "w", newline="") as file:
            fieldnames = list(results[0].keys())
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        self.stdout.write(f"CTA export is ready! Find it here: {filepath}.")
