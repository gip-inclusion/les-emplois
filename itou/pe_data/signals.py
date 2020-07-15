from allauth.account.signals import user_logged_in
from django.dispatch import receiver

from itou.allauth.peamu.provider import PEAMUProvider


@receiver(user_logged_in)
def user_has_logged(sender, **kwargs):
    """
    Get token from succesful login for async PE API calls
    """
    login = kwargs.get("sociallogin")
    if login and login.account.provider == PEAMUProvider.id:
        # TBD:  API calls
        print(f"token: {login.token}")
