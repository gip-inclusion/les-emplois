from anymail.signals import tracking
from django.dispatch import receiver

from .models import RejectedEmailEventData


def store_rejected_email_event(event):
    # Anymail understands Mailjet's webhook for us and translates its results
    # https://anymail.readthedocs.io/en/stable/sending/tracking/#normalized-tracking-event
    if event.event_type == "rejected":
        # the email adress we attempted to send a message to
        recipient = event.recipient
        # The reason for rejection, can be one of:
        # 'invalid': bad email address format.
        # 'bounced': bounced recipient. (In a 'rejected' event, indicates the recipient
        # is on your ESP’s prior-bounces suppression list.)
        # 'timed_out': your ESP is giving up after repeated transient delivery failures
        # (which may have shown up as 'deferred' events).
        # 'blocked': your ESP’s policy prohibits this recipient.
        # 'spam': the receiving MTA or recipient determined the message is spam.
        # (In a 'rejected' event, indicates the recipient is on your ESP’s prior-spam-complaints suppression list.)
        # 'unsubscribed': the recipient is in your ESP’s unsubscribed suppression list.
        # 'other': some other reject reason; examine the raw esp_event.
        reason = event.reject_reason
        rejected_email = RejectedEmailEventData(recipient=recipient, reason=reason)
        rejected_email.save()


@receiver(tracking)
def handle_email_webhooks(sender, event, esp_name, **kwargs):
    # Wrapper in order to decouple the signal and its management
    store_rejected_email_event(event)
