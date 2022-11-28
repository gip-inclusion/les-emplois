"""
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

    help = "Build Metabase final tables."

    @timeit
    def handle(self, **options):
        send_slack_message(":rocket: Démarrage de la mise à jour des tables SQL secondaires")
        build_final_tables()
        send_slack_message(":white_check_mark: Mise à jour des tables SQL secondaires terminée")
