from itou.utils.command import BaseCommand
from itou.utils.slack import send_slack_message


class Command(BaseCommand):
    help = "Send a slack message to the configured webhook, thus channel."

    def add_arguments(self, parser):
        parser.add_argument("message", help="The message to be sent")

    def handle(self, message, **options):
        send_slack_message(message)
