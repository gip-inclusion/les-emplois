from django.conf import settings

import itou.utils.emails as emails
from itou.utils.actors import REGISTRY


# Must init a Registry object for django_dramatiq_pg
# For convenience, REGISTRY is defined in `__init__.py`


@REGISTRY.actor(store_results=True, max_retries=settings.SEND_EMAIL_NB_RETRIES)
def async_send_messages(serializable_email_messages):
    """
        Async email sending "delegate"

        This function sends emails with the backend defined in `settings.ASYNC_EMAIL_BACKEND`
        and is trigerred by an email backend wrappper: `AsyncEmailBackend`.

        As it is decorated as a Dramatiq actor, all parameters must be serializable via a JSON dump.

        Dramatiq stores some data via the broker persistence mechanism (Redis | RabbitMQ | PGCONNECT)
        for RPC/async/retry purposes.

        In order to send data to a remote broker and perform callback function call on the client,
        Dramatiq must use a serialization mechanism to send "over the wire" (PGCONNECT here).

        In this case for a `@actor`, data sent by Dramatiq are:
        * the function name (to use as a callback)
        * its call parameters (to make the call)

        The main parameter is a list of `EmailMessage` objects to be send.

        By design, an `EmailMessage` instance holds references to some non-serializable ressources:
        * a connection to the email backend (if not `None`)
        * inner locks for atomic/threadsafe operations
        * ...

        Making `EmailMessage` serializable is the purpose of `serializeEmailMessage` and `deserializeEmailMessage`.

        If there are many async tasks to be defined or for specific objects,
        it may be better to use a custom serializer.

        By design, this function must return the number of email correctly processed.
    """

    count = 0

    for message in serializable_email_messages:
        emails.deserializeEmailMessage(message).send()
        count += 1

    return count
