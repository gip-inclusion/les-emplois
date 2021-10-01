from allauth.account.signals import user_logged_in  # , user_logged_out
from anymail.signals import tracking
from django.conf import settings
from django.dispatch import receiver
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode

from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.utils.urls import get_absolute_url

from .models import ExternalDataImport, RejectedEmailEventData
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


def log_out_from_france_connect(request, user):
    # https://django-allauth.readthedocs.io/en/latest/signals.html
    fc_token = request.session.get(settings.FRANCE_CONNECT_SESSION_TOKEN)
    fc_state = request.session.get(settings.FRANCE_CONNECT_SESSION_STATE)
    # Note: if you need session data, fetch them BEFORE calling super() ;)
    # ajax_response = super().post(*args, **kwargs)

    # Logouts user from the app and from France Connect (FC).
    if fc_token:  # and not settings.ITOU_ENVIRONMENT == "DEV":
        # In the dev environment, user is not logged out from FC because for some reason
        # on FC’s end, it throws an error and crash so post-logout
        # redirection is not performed
        params = {"id_token": fc_token, "state": fc_state}
        fc_base_logout_url = get_absolute_url(reverse("france_connect:logout"))
        fc_logout_url = f"{fc_base_logout_url}?{urlencode(params)}"
        return HttpResponseRedirect(fc_logout_url)


@receiver(user_logged_in)
def user_logged_in_receiver(sender, **kwargs):
    # Wrapper required to mock the db_task of Huey in unit tests
    import_user_pe_data_on_peamu_login(sender, **kwargs)


# @receiver(user_logged_out)
# def user_logged_out_receiver(request, user, **kwargs):
#     log_out_from_france_connect(request, user)


@receiver(tracking)
def handle_email_webhooks(sender, event, esp_name, **kwargs):
    # Wrapper in order to decouple the signal and its management
    store_rejected_email_event(event)
