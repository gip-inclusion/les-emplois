from allauth.account.adapter import DefaultAccountAdapter

from django.http import HttpResponseRedirect
from django.urls import reverse


class MyAccountAdapter(DefaultAccountAdapter):
    def respond_user_inactive(self, request, user):
        """
        Overrides default allauth adapter which otherwise loses user info.
        Here is how to override an allauth adapter :
        https://django-allauth.readthedocs.io/en/latest/advanced.html#custom-redirects
        Here is the original adapter code:
        https://github.com/pennersr/django-allauth/blob/master/allauth/account/adapter.py#L452
        """
        return HttpResponseRedirect(
            reverse("signup:account_inactive", kwargs={"user_uuid": user.uuid})
        )
