from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth.peamu.provider import PEAMUProvider

from . import apis, data_import, models


@receiver(user_logged_in)
def user_has_logged_in(sender, **kwargs):
    """
    Get token from succesful login for (a)sync PE API calls
    """
    login = kwargs.get("sociallogin")

    # At this point, sender is a user object
    user = kwargs.get("user")

    if user and login and login.account.provider == PEAMUProvider.id:
        # Format and store data if needed
        pe_data_import = models.ExternalDataImport.objects.for_user(user).filter(
            source=models.ExternalDataImport.DATA_SOURCE_PE_CONNECT
        )

        if not pe_data_import.exists() or pe_data_import.last().status == models.ExternalDataImport.STATUS_FAILED:
            # Fetch data if not already done or failed
            extra_data = apis.get_aggregated_user_data(login.token)
            # Store and dispatch as key / value pairs
            data_import.import_pe_external_user_data(user, extra_data)

        # FIXME: remove later
        print(f"token: {login.token}")
