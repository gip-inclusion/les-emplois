from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, TemplateView

from itou.emails.models import EmailConfirmation
from itou.users.notifications import PasswordChangedNotification
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.requests import get_client_ip, get_http_user_agent
from itou.utils.views import NextRedirectMixin
from itou.www.accounts.forms import ChangePasswordForm


# TODO: migrate rate_limit functionality from allauth, or replace it.
# @method_decorator(rate_limit(action="change_password"), name="dispatch")
@method_decorator(sensitive_post_parameters("oldpassword", "password", "password1", "password2"), name="dispatch")
class PasswordChangeView(NextRedirectMixin, FormView):
    template_name = "account/password_change.html"
    form_class = ChangePasswordForm
    success_url = reverse_lazy("dashboard:index")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()

        # Default behavior of Django to invalidate all sessions on password change, but we preserve the session.
        user = form.user
        update_session_auth_hash(self.request, user)

        # Notify the user in-site and by email.
        messages.add_message(self.request, messages.SUCCESS, "Mot de passe modifié avec succès.")
        PasswordChangedNotification(
            user,
            timestamp=timezone.now(),
            ip=get_client_ip(self.request),
            user_agent=get_http_user_agent(self.request),
        ).send()

        return super().form_valid(form)


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
