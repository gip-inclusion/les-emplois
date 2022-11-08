"""
Command runned manually from time to time by C2 data analysts via a github action.

This commands only runs the quick final SQL requests otherwise completed at the end of
the daily `populate_metabase_itou` and the weekly `populate_metabase_fluxiae` commands.

This is convenient for our data analysts to quickly apply their latest merged PR changes without
having to complete a long `populate_metabase_itou` command which takes several hours.
"""

from django.core.management.base import BaseCommand

from itou.metabase.management.commands._utils import build_final_tables
from itou.utils.python import timeit
from itou.utils.slack import send_slack_message


class Command(BaseCommand):
    """
    Run Metabase final SQL requests.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a dry prefix added to their name, to avoid
    touching any real table, and injects only a sample of data.

    To populate alternate tables with sample data:
        django-admin build_metabase_final_tables --dry-run

    When ready:
        django-admin build_metabase_final_tables
    """

    help = "Build Metabase final tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Populate alternate tables with sample data"
        )

    @timeit
    def handle(self, dry_run=False, **options):
        send_slack_message(":rocket: Démarrage de la mise à jour des tables SQL secondaires")
        build_final_tables(dry_run=dry_run)
        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
        send_slack_message(":white_check_mark: Mise à jour des tables SQL secondaires terminée")
