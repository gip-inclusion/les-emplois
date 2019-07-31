"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import SignupView

from django.conf import settings
from django.db import transaction

from itou.accounts import forms


class PrescriberSignupView(SignupView):

    form_class = forms.PrescriberSignupForm
    template_name = 'accounts/prescriber/signup.html'

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)
