from allauth.account.signals import user_logged_in
from anymail.signals import tracking
from django.dispatch import receiver

from itou.allauth_adapters.peamu.provider import PEAMUProvider

from .models import ExternalDataImport
from .tasks import huey_import_user_pe_data


def import_user_pe_data_on_peamu_login(sender, **kwargs):
    """
    Get token from succesful login for async PE API calls
    This is a receiver for a allauth signal (`user_logged_in`)
    """
    login = kwargs.get("sociallogin")
    user = kwargs.get("user")

    # This part only for users login-in with PE
    if user and login and login.account.provider == PEAMUProvider.id:
        # Format and store data if needed
        latest_pe_data_import = user.externaldataimport_set.pe_sources().first()
        if latest_pe_data_import is None or latest_pe_data_import.status != ExternalDataImport.STATUS_OK:
            # No data for user or the import failed last time
            # Async via Huey
            huey_import_user_pe_data(user, str(login.token), latest_pe_data_import)


@receiver(user_logged_in)
def user_logged_in_receiver(sender, **kwargs):
    # Wrapper required to mock the db_task of Huey in unit tests
    import_user_pe_data_on_peamu_login(sender, **kwargs)


@receiver(tracking)  # add weak=False if inside some other function/class
def handle_blocked_emails(sender, event, esp_name, **kwargs):
    # Anymail understands Mailjet's webhook for us and translates its results
    # https://anymail.readthedocs.io/en/stable/sending/tracking/#normalized-tracking-event
    if event.event_type == 'rejected':
        # the email adress we attempted to send a message to
        recipient = event.recipient
        # The reason for rejection, can be one of:
        # 'invalid': bad email address format.
        # 'bounced': bounced recipient. (In a 'rejected' event, indicates the recipient is on your ESP’s prior-bounces suppression list.)
        # 'timed_out': your ESP is giving up after repeated transient delivery failures (which may have shown up as 'deferred' events).
        # 'blocked': your ESP’s policy prohibits this recipient.
        # 'spam': the receiving MTA or recipient determined the message is spam. (In a 'rejected' event, indicates the recipient is on your ESP’s prior-spam-complaints suppression list.)
        # 'unsubscribed': the recipient is in your ESP’s unsubscribed suppression list.
        # 'other': some other reject reason; examine the raw esp_event.
        reason = event.reject_reason
