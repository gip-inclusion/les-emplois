import os
import pathlib

from django.conf import settings
from django.core.management import call_command
from django.db import connection

from itou.fixtures.django.dynamic import load_dynamic
from itou.utils.command import BaseCommand
from itou.utils.enums import ItouEnvironment


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    ALL_STEPS = "all"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order in the dict is the order in which the function are going to be called
        self.STEP_TO_OPERATION = {
            "reference": self.populate_reference,
            "fixtures": self.populate_fixtures,
            "dynamic": self.populate_dynamic,
        }

    def add_arguments(self, parser):
        parser.add_argument("steps", nargs="+", choices=[self.ALL_STEPS, *sorted(self.STEP_TO_OPERATION)])

    def handle(self, *, steps, **options):
        if settings.ITOU_ENVIRONMENT == ItouEnvironment.PROD:
            raise RuntimeError("Nope.")

        if os.getenv("SKIP_POPULATE_DB"):
            self.logger.info("SKIP_POPULATE_DB set - skipping")
            return

        if self.ALL_STEPS in steps:
            if len(steps) != 1:
                raise RuntimeError('"all" step should be the only step specified')
            steps = list(self.STEP_TO_OPERATION)

        for step in steps:
            self.logger.info("Starting step=%s", step)
            self.STEP_TO_OPERATION[step]()

    def populate_reference(self):
        sql_fixtures_dir = pathlib.Path(settings.APPS_DIR, "fixtures", "postgres")
        for filename in [
            "cities_city.sql",
            "asp_commune.sql",
            "asp_department.sql",
            "asp_country.sql",
            "jobs_rome.sql",
            "jobs_appellation.sql",
        ]:
            self.logger.info("Loading %s", filename)
            connection.client.runshell(["--file", sql_fixtures_dir / filename])

        qpv_file = "itou/geo/fixtures/QPV_2024.json"
        self.logger.info("Loading %s", qpv_file)
        call_command("loaddata_bulk", qpv_file)

    def populate_fixtures(self):
        django_fixtures_dir = pathlib.Path(settings.APPS_DIR, "fixtures", "django")
        # loaddata_bulk expects a list of path starting with itou
        json_fixtures = [path.relative_to(settings.ROOT_DIR) for path in django_fixtures_dir.glob("*.json")]
        self.logger.info("Loading %s", ", ".join(sorted(map(str, json_fixtures))))
        call_command("loaddata_bulk", *json_fixtures)

    def populate_dynamic(self):
        self.logger.info("Loading dynamic fixtures")
        load_dynamic()
