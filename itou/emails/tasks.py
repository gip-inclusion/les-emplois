import logging
from itertools import batched

import sentry_sdk
from anymail.exceptions import AnymailError
from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage
from django.db import ProgrammingError, connection, transaction
from huey.contrib.djhuey import on_commit_task
from huey.exceptions import CancelExecution
from requests.exceptions import InvalidJSONError

from itou.emails.models import Email


logger = logging.getLogger("itou.emails")

# Brevo max total number of recipients (TO, CC, BCC) per API call.
# https://developers.brevo.com/reference/send-transac-email
_BREVO_MAX_RECIPIENTS = 2000
_EMAIL_KEYS = ("from_email", "cc", "bcc", "subject", "body")


def sanitize_recipients(email_message):
    """
    Brevo API has a **2000** number limit for anytype of email recipient:
    * TO
    * CC
    * BCC

    This function:
    * partitions email recipients with more than 2000 elements
    * creates new emails with a number of recipients in the Brevo limit
    * **only** checks for `TO` recipients owerflows

    `email_message` is an EmailMessage object (not serialized)

    Returns a **list** of "sanitized" emails.
    """

    if len(email_message.to) <= _BREVO_MAX_RECIPIENTS:
        # We're ok, return a list containing the original message
        return [email_message]

    sanitized_emails = []
    to_chunks = batched(email_message.to, _BREVO_MAX_RECIPIENTS)
    # We could also combine to, cc and bcc, but it's useless for now

    for to_chunk in to_chunks:
        copy_kvs = {k: email_message.__dict__[k] for k in _EMAIL_KEYS}
        copy_email = EmailMessage(**copy_kvs)
        copy_email.to = to_chunk
        sanitized_emails.append(copy_email)

    return sanitized_emails


# Custom async email backend wrapper
# ----------------------------------

# Settings are explicit for humans, but this is what Huey needs
_NB_RETRIES = int(
    settings.SEND_EMAIL_RETRY_TOTAL_TIME_IN_SECONDS / settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS
)


@on_commit_task(retries=_NB_RETRIES, retry_delay=settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS, context=True)
def _async_send_message(email_id, *, task=None):
    with transaction.atomic():
        try:
            email = Email.objects.select_for_update(of=("self",), no_key=True).get(pk=email_id)
        except Email.DoesNotExist:
            # Email deleted from django admin, stop trying to send it.
            logger.warning("Not sending email_id=%d, it does not exist in the database.", email_id)
            return
        message = EmailMessage(
            from_email=email.from_email,
            reply_to=email.reply_to,
            to=email.to,
            cc=email.cc,
            bcc=email.bcc,
            subject=email.subject,
            body=email.body_text,
        )
        try:
            with get_connection(backend=settings.ASYNC_EMAIL_BACKEND) as connection:
                connection.send_messages([message])
        except AnymailError as e:
            if e.response is not None:
                try:
                    email.esp_response = e.response.json()
                except InvalidJSONError:
                    logger.exception(
                        "Received invalid response from Brevo, email_id=%d. Payload: %s",
                        email_id,
                        e.response.text,
                    )
            else:
                logger.exception("Could not reach Email Service Provider.")
            success = False
        else:
            try:
                email.esp_response = message.anymail_status.esp_response.json()
            except AttributeError:
                # anymail_status is None in development and default test environments.
                if settings.ASYNC_EMAIL_BACKEND in [
                    "django.core.mail.backends.console.EmailBackend",
                    "django.core.mail.backends.locmem.EmailBackend",
                ]:
                    success = True
                else:
                    raise
            else:
                # Brevo returns a "messageId" (or "messageIds" for batch sends) on success,
                # and doesn't raise AnymailError on failure until the HTTP response is not 2xx.
                success = True
        email.save(update_fields=["esp_response"])
        # Commit the email status to the DB.
    if not success:
        if task.retries:
            raise CancelExecution(retry=True)
        # Last attempt failed, let’s get a report.
        sentry_sdk.capture_message(f"Could not send {email.pk=}.", "error")
        return 0
    return 1


class AsyncEmailBackend(BaseEmailBackend):
    """Custom async email backend wrapper

    Decorating a method with `@task` does not work (no static context).
    Only functions can be Huey tasks.

    This class:
    * wraps an email backend defined in `settings.ASYNC_EMAIL_BACKEND`
    * delegate the actual email sending to a function with *serializable* parameters

    See `_async_send_messages` for more on details on the serialization and
    asynchronous processing
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return
        if not connection.in_atomic_block:
            raise ProgrammingError("Sending email requires an active database transaction.")
        emails_count = 0
        for message in email_messages:
            for sanitized_email in sanitize_recipients(message):
                # Send each email in a separate task, so that Huey retry mecanism only
                # retries the failed email.
                email = Email.from_email_message(sanitized_email)
                email.save()
                if not [*sanitized_email.to, *sanitized_email.cc, *sanitized_email.bcc]:
                    logger.error(f"Email {email.pk} has no recipients, ignoring.", stack_info=True)
                    continue
                emails_count += 1
                _async_send_message(email.pk)
        return emails_count
