from django.core.management.base import BaseCommand

from itou.siae_evaluations.models import EvaluatedSiae
from itou.utils.emails import get_email_message, send_email_messages


def get_email_patch_siae(to):
    context = {}
    subject = "siae_evaluations/email/patch_siaes_subject.txt"
    body = "siae_evaluations/email/patch_siaes_body.txt"
    return get_email_message(to, context, subject, body)


class Command(BaseCommand):
    """
    To send emails:
        django-admin patch_siae_emails
    """

    help = "Send emails to SIAE admin users, if their SIAE is in named evaluation_campaign and in selected state"

    def handle(self, **options):

        evaluation_campaign_name = "Campagne de janvier à décembre 2021 - partie 2"
        evsiaes = (
            evsiae
            for evsiae in EvaluatedSiae.objects.filter(evaluation_campaign__name=evaluation_campaign_name)
            if evsiae.state in ["PENDING", "SUBMITTABLE"]
        )
        send_email_messages(get_email_patch_siae(evsiae.siae.active_admin_members) for evsiae in evsiaes)
