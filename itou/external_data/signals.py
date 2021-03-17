from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth_adapters.peamu.provider import PEAMUProvider

from .models import ExternalDataImport
from .tasks import import_pe_data


def save_pe_token_on_peamu_login(sender, **kwargs):
    """
    Get token from succesful login for async PE API calls
    This is a receiver for a allauth signal (`user_logged_in`)
    """
    login = kwargs.get("sociallogin")
    user = kwargs.get("user")

    # This part only for users login-in with PE
    if user and login and login.account.provider == PEAMUProvider.id:
        # Format and store data if needed
        pe_data_import = user.externaldataimport_set.pe_imports()

        # If no data for user or import failed last time
        if not pe_data_import.exists() or pe_data_import.first().status != ExternalDataImport.STATUS_OK:
            # Async via Huey
            import_pe_data(user.pk, str(login.token))


@receiver(user_logged_in)
def user_logged_in_receiver(sender, **kwargs):
    # Wrapper required to mock the db_task of Huey in unit tests
    save_pe_token_on_peamu_login(sender, **kwargs)
