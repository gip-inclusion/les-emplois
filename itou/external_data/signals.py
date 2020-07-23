from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth.peamu.provider import PEAMUProvider

from . import apis, data_import, models


@receiver(user_logged_in)
def user_has_logged(sender, **kwargs):
    """
    Get token from succesful login for async PE API calls
    """
    login = kwargs.get("sociallogin")

    # At this point, sender is a user object
    user = kwargs.get("user")

    if user and login and login.account.provider == PEAMUProvider.id:
        # Format and store data if needed
        pe_data_import = models.DataImport.objects.for_user(user).filter(
            source=models.DataImport.DATA_SOURCE_PE_CONNECT
        )

        if not pe_data_import.exists() or pe_data_import.last().status == models.DataImport.STATUS_FAILED:
            # fetch data
            extra_data = apis.get_aggregated_user_data(login.token)
            # Store and dispatch as kvs
            data_import.import_pe_external_user_data(user, extra_data)
            print("Extra data:", extra_data)

        # FIXME: remove later
        print(f"token: {login.token}")
