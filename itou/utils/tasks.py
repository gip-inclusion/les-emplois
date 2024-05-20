import logging
from functools import partial

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage
from django.db import ProgrammingError, connection, transaction
from huey.contrib.djhuey import task

from itou.utils.iterators import chunks


# Reduce verbosity of huey logs (INFO by default)
logging.getLogger("huey").setLevel(logging.WARNING)


# Mailjet max number of recipients (CC, BCC, TO)
_MAILJET_MAX_RECIPIENTS = 50
_EMAIL_KEYS = ("from_email", "cc", "bcc", "subject", "body")


def sanitize_mailjet_recipients(email_message):
    """
    Mailjet API has a **50** number limit for anytype of email recipient:
    * TO
    * CC
    * BCC

    This function:
    * partitions email recipients with more than 50 elements
    * creates new emails with a number of recipients in the Mailjet limit
    * **only** checks for `TO` recipients owerflows

    `email_message` is an EmailMessage object (not serialized)

    Returns a **list** of "sanitized" emails.
    """

    if len(email_message.to) <= _MAILJET_MAX_RECIPIENTS:
        # We're ok, return a list containing the original message
        return [email_message]

    sanitized_emails = []
    to_chunks = chunks(email_message.to, _MAILJET_MAX_RECIPIENTS)
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


def _serializeEmailMessage(email_message):
    """
    Returns a dict with `EmailMessage` instance content serializable via Pickle (remote data sending concern).

    **Important:**
    Some important features & fields of `EmailMessage` are not "serialized":
    * attachments
    * special options of the messages

    Just the bare minimum used by the app is kept for serialization.

    This functions works in pair with `_deserializeEmailMessage`.
    """
    return {
        "subject": email_message.subject,
        "to": email_message.to,
        "from_email": email_message.from_email,
        "reply_to": email_message.reply_to,
        "cc": email_message.cc,
        "bcc": email_message.bcc,
        # FIXME: if needed "headers": email_message.headers,
        "body": email_message.body,
    }


def _deserializeEmailMessage(serialized_email_message):
    return EmailMessage(**serialized_email_message)


# TODO(François): Preserved for in-flight tasks, drop after a few days.
@task(retries=_NB_RETRIES, retry_delay=settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS)
def _async_send_messages(serializable_email_messages):
    """
    An `EmailMessage` instance holds references to some non-serializable
    ressources, such as a connection to the email backend (if not `None`).

    Making `EmailMessage` serializable is the purpose of
    `_serializeEmailMessage` and `_deserializeEmailMessage`.
    """
    messages = []
    with get_connection(backend=settings.ASYNC_EMAIL_BACKEND) as connection:
        for serialized_email in serializable_email_messages:
            email = _deserializeEmailMessage(serialized_email)
            messages.extend(sanitize_mailjet_recipients(email))
        connection.send_messages(messages)
    return len(messages)


@task(retries=_NB_RETRIES, retry_delay=settings.SEND_EMAIL_DELAY_BETWEEN_RETRIES_IN_SECONDS)
def _async_send_message(serialized_email):
    """
    An `EmailMessage` instance holds references to some non-serializable
    ressources, such as a connection to the email backend (if not `None`).

    Making `EmailMessage` serializable is the purpose of
    `_serializeEmailMessage` and `_deserializeEmailMessage`.
    """
    with get_connection(backend=settings.ASYNC_EMAIL_BACKEND) as connection:
        email = _deserializeEmailMessage(serialized_email)
        connection.send_messages([email])
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
        for email in email_messages:
            for mjemail in sanitize_mailjet_recipients(email):
                emails_count += 1
                # Send each email in a separate task, so that Huey retry mecanism only
                # retries the failed email.
                transaction.on_commit(partial(_async_send_message, _serializeEmailMessage(mjemail)))
        return emails_count
