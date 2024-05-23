# TODO(François): Preserved for in-flight tasks, drop file after a few days.
import logging

import sentry_sdk
from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.message import EmailMessage
from django.db import transaction
from huey.contrib.djhuey import task


# Reduce verbosity of huey logs (INFO by default)
logging.getLogger("huey").setLevel(logging.WARNING)


_NB_RETRIES = int(
    settings.SEND_EMAIL_RETRY_TOTAL_TIME_IN_SECONDS / settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS
)


def _deserializeEmailMessage(serialized_email_message):
    return EmailMessage(**serialized_email_message)


@task(retries=_NB_RETRIES, retry_delay=settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS, context=True)
def _async_send_message(serialized_email, task):
    email = _deserializeEmailMessage(serialized_email)
    with transaction.atomic():
        with get_connection(backend=settings.ASYNC_EMAIL_BACKEND) as connection:
            connection.send_messages([email])
    # Mailjet has a global flag for an email to indicate success.
    # Anymail iterates over recipients and assign each a status, following its
    # documented API. Mailjet indicating success is good enough.
    # https://dev.mailjet.com/email/guides/send-api-v31/
    try:
        [result] = email.anymail_status.esp_response.json()["Messages"]
    except AttributeError:
        # esp_response is None in development environments.
        pass
    else:
        if result["Status"] != "success":
            if task and task.retries:
                raise Exception("Huey, please retry this task.")
            sentry_sdk.capture_message(f"Could not send email: {result}", "error")
            return 0
    return 1
