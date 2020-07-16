from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth.peamu.provider import PEAMUProvider

from . import apis, extras


@receiver(user_logged_in)
def user_has_logged(sender, **kwargs):
    """
    Get token from succesful login for async PE API calls
    """
    login = kwargs.get("sociallogin")
    user = kwargs.get("user")
    if user and login and login.account.provider == PEAMUProvider.id:
        # At this point, sender is a user object
        # Format and store data
        extra_data = apis.get_aggregated_user_data(login.token)
        extras.import_extra_user_data(user, extra_data)
        # FIXME: remove
        print(f"token: {login.token}")
        print("Extra data:", extra_data)
