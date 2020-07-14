from allauth.account.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def user_has_logged(sender, **kwargs):
    print("Hello from sender :" + str(sender))
    login = kwargs.get("sociallogin")
    if login:
        print(login.token)
