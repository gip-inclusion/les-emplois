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
        extra_data = models.ExternalUserData.objects.for_user(user).first()

        if not extra_data or extra_data.status == models.ExternalUserData.STATUS_FAILED:
            extra_data = apis.get_aggregated_user_data(login.token)
            data_import.import_pe_external_user_data(user, extra_data)
            print("Extra data:", extra_data)

        # FIXME: remove later
        print(f"token: {login.token}")
