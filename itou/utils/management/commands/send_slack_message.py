"""
This commands only runs the quick final SQL requests otherwise completed at the end of
the daily `populate_metabase_itou` and the weekly `populate_metabase_fluxiae` commands.

This is convenient for our data analysts to quickly apply their latest merged PR changes without
having to complete a long `populate_metabase_itou` command which takes several hours.
"""

from django.core.management.base import BaseCommand

from itou.utils.slack import send_slack_message


class Command(BaseCommand):

    help = "Send a slack message to the configured webhook, thus channel."

    def add_arguments(self, parser):
        parser.add_argument("message", help="The message to be sent")

    def handle(self, message, **options):
        send_slack_message(message)
