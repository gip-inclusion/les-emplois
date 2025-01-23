from allauth.account.views import PasswordChangeView
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from itou.emails.models import EmailConfirmation
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.views import NextRedirectMixin


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


class PasswordResetDoneView(LoginNotRequiredMixin, TemplateView):
    template_name = "account/password_reset_done.html"


class PasswordResetFromKeyDoneView(LoginNotRequiredMixin, TemplateView):
    template_name = "account/password_reset_from_key_done.html"


class AccountInactiveView(LoginNotRequiredMixin, TemplateView):
    template_name = "account/account_inactive.html"


class EmailVerificationSentView(LoginNotRequiredMixin, TemplateView):
    template_name = "account/verification_sent.html"


class ConfirmEmailView(LoginNotRequiredMixin, NextRedirectMixin, TemplateView):
    template_name = "account/email_confirm.html"

    def get(self, *args, **kwargs):
        try:
            self.object = self.get_object()
            self.logout_other_user(self.object)
        except EmailConfirmation.DoesNotExist:
            self.object = None

        return self.render_to_response(self.get_context_data())

    def post(self, *args, **kwargs):
        def fail():
            self.object = None
            return self.render_to_response(self.get_context_data())

        try:
            self.object = self.get_object()
        except EmailConfirmation.DoesNotExist:
            # A user has made a POST request with an invalid key.
            return fail()

        self.logout_other_user(self.object)

        if self.object.confirm(self.request, perform_login_on_success=True) is None:
            # A user has made a POST request with an expired key, or to a previously-verified email.
            # Possibly the web page has become out of date since they followed the link.
            return fail()

        # Succeed.
        return redirect(self.get_redirect_url())

    def logout_other_user(self, confirmation):
        """
        In the event someone clicks on an email confirmation link
        for one account while logged into another account,
        logout of the currently logged in account.
        """
        if self.request.user.is_authenticated and self.request.user.pk != confirmation.email_address.user_id:
            logout(self.request)

    def get_object(self, queryset=None):
        key = self.kwargs["key"]
        emailconfirmation = EmailConfirmation.from_key(key)
        if not emailconfirmation:
            raise EmailConfirmation.DoesNotExist()
        return emailconfirmation

    def get_queryset(self):
        return EmailConfirmation.objects.all_valid().select_related("email_address__user")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["confirmation"] = self.object
        return context

    def get_redirect_url(self):
        if self.get_next_url():
            return self.get_next_url()
        # NOTE: User will be authenticated here, but allauth has some code for handling anonymous users,
        # sending to settings.LOGIN_URL (for us set to Django default).
        return settings.LOGIN_REDIRECT_URL
