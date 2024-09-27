import os

import tenacity
from django.conf import settings
from django.db import DatabaseError, connection

from itou.utils.command import BaseCommand


sleep_secs = 5


class Command(BaseCommand):
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(DatabaseError),
        stop=tenacity.stop_after_attempt(120),
        wait=tenacity.wait_fixed(sleep_secs),
    )
    def handle(self, **options):
        print(settings.DATABASES)
        for key in os.environ:
            if key.startswith("POSTGRESQL_ADDON_DIRECT_"):
                print(os.getenv(key))

        self.stderr.write(f"Attempting to connect to the database. Sleep {sleep_secs} seconds when not available.")
        with connection.cursor() as c:
            c.execute("SELECT 1")
