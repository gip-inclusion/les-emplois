import asyncio

from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth.peamu.provider import PEAMUProvider

from .apis.pe_connect import async_import_user_data, import_user_data
from .models import ExternalDataImport


@receiver(user_logged_in)
def user_logged_in(sender, **kwargs):
    """
    Get token from succesful login for (a)sync PE API calls
    This is a receiver for a allauth signal (`user_logged_in`)
    """
    login = kwargs.get("sociallogin")

    # At this point, sender is a user object
    user = kwargs.get("user")

    # This part only for users login-in with PE
    if user and login and login.account.provider == PEAMUProvider.id:
        # Format and store data if needed
        pe_data_import = ExternalDataImport.objects.for_user(user).filter(
            source=ExternalDataImport.DATA_SOURCE_PE_CONNECT
        )

        # If no data for user or import failed last time
        if not pe_data_import.exists() or pe_data_import.last().status != ExternalDataImport.STATUS_OK:
            # Store and dispatch as key / value pairs

            # SYNC:
            # import_user_data(user, login.token)

            # ASYNC:
            asyncio.run(async_import_user_data(user, login.token))
