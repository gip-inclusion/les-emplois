from allauth.account import app_settings
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.account.utils import send_email_confirmation
from allauth.account.views import ConfirmEmailView as BaseConfirmEmailView
from django.core import signing
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import View

from itou.utils.auth import LoginNotRequiredMixin


class ExpiredConfirmationMixin:
    def get_object_with_expired_key(self):
        key = self.kwargs["key"]
        try:
            pk = signing.loads(key, salt=app_settings.SALT)
            return EmailConfirmationHMAC(EmailAddress.objects.get(pk=pk, verified=False)).email_address
        except (
            signing.SignatureExpired,
            signing.BadSignature,
            EmailAddress.DoesNotExist,
        ):
            raise Http404()


class ConfirmEmailView(BaseConfirmEmailView, ExpiredConfirmationMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object is None:
            try:
                self.get_object_with_expired_key()  # Raises error for invalid keys.
                key = self.kwargs["key"]
            except Http404:
                key = None
        context.update({"provided_key": key})
        return context


class ResendConfirmationView(LoginNotRequiredMixin, ExpiredConfirmationMixin, View):
    def fail(self):
        return redirect(reverse("signup:choose_user_kind"))

    def get(self, request, *args, **kwargs):
        # Validate key.
        try:
            email_address = self.get_object_with_expired_key()
        except Http404:
            return self.fail()

        # Do not send a confirmation to a verified address.
        if email_address.verified:
            return self.fail()

        send_email_confirmation(request, email_address.user, email_address.email)
        return redirect(reverse("account_email_verification_sent"))
