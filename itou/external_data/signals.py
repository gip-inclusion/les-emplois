import asyncio

from allauth.account.signals import user_logged_in
from django.conf import settings
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
        pe_data_import = ExternalDataImport.objects.pe_import_for_user(user)

        # If no data for user or import failed last time
        if not pe_data_import.exists() or pe_data_import.first().status != ExternalDataImport.STATUS_OK:
            if settings.EXTERNAL_DATA_SYNC_API_CALL:
                # SYNC (fallback):
                import_user_data(user, login.token)
            else:
                # ASYNC (default):
                asyncio.run(async_import_user_data(user, login.token))
