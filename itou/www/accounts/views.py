from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, TemplateView

from itou.emails.models import EmailConfirmation
from itou.users.notifications import PasswordChangedNotification, PasswordResetSuccessNotification
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.requests import get_client_ip, get_http_user_agent
from itou.utils.views import NextRedirectMixin, logout_with_message
from itou.www.accounts import forms


INTERNAL_RESET_SESSION_KEY = "_password_reset_key"


# TODO: migrate rate_limit functionality from allauth, or replace it.
# @method_decorator(rate_limit(action="change_password"), name="dispatch")
@method_decorator(sensitive_post_parameters("oldpassword", "password", "password1", "password2"), name="dispatch")
class PasswordChangeView(NextRedirectMixin, FormView):
    template_name = "account/password_change.html"
    form_class = forms.ChangePasswordForm
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


class PasswordResetView(LoginNotRequiredMixin, NextRedirectMixin, FormView):
    form_class = forms.ResetPasswordForm
    success_url = reverse_lazy("accounts:account_reset_password_done")
    template_name = "account/password_reset.html"

    # TODO: migrate or replace rate-limiting code from allauth
    def form_valid(self, form):
        form.save(self.request)
        # Pass the email in the querystring so that it can displayed in the template.
        args = urlencode({"email": form.data["email"]})
        return HttpResponseRedirect(f"{self.get_success_url()}?{args}")

    def form_invalid(self, form):
        """
        Avoid user enumeration: We deliberately hide a non-existing email error by redirecting to the success page.
        """
        # Pass the email in the querystring so that it can displayed in the template.
        args = urlencode({"email": form.data.get("email", "")})
        return HttpResponseRedirect(f"{self.get_success_url()}?{args}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["login_url"] = self.passthrough_next_url(reverse("accounts:account_login"))
        return context


# TODO: migrate or replace rate-limiting from allauth
# @method_decorator(rate_limit(action="reset_password_from_key"), name="dispatch")
class PasswordResetFromKeyView(LoginNotRequiredMixin, NextRedirectMixin, FormView):
    form_class = forms.ResetPasswordKeyForm
    reset_url_key = "set-password"
    success_url = reverse_lazy("accounts:account_reset_password_from_key_done")
    template_name = "account/password_reset_from_key.html"
    _user_is_new = None

    def user_is_new(self):
        if self._user_is_new is None:
            self._user_is_new = self.reset_user and not self.reset_user.last_login
        return self._user_is_new

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.reset_user
        kwargs["temp_key"] = self.key
        return kwargs

    def form_valid(self, form):
        form.save()
        user = self.reset_user
        # TODO: restore or remove this cache clear when you migrate/adapt the rate-limiting
        """
        if user:
            # User successfully reset the password, clear any
            # possible cache entries for all email addresses.
            for email in EmailAddress.objects.filter(user_id=user.pk):
                adapter._delete_login_attempts_cached_email(request, email=email.email)
        """

        messages.add_message(self.request, messages.SUCCESS, "Mot de passe modifié avec succès.")
        PasswordResetSuccessNotification(
            user,
            timestamp=timezone.now(),
            ip=get_client_ip(self.request),
            user_agent=get_http_user_agent(self.request),
        ).send()

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["action_url"] = reverse(
            "accounts:account_reset_password_from_key",
            kwargs={
                "uidb36": self.kwargs["uidb36"],
                "key": self.kwargs["key"],
            },
        )
        context["user_is_new"] = self.user_is_new()
        context["action_text"] = f"{'Enregistrer' if self.user_is_new() else 'Modifier'} le mot de passe"
        return context

    def get_success_url(self):
        if self.user_is_new():
            # clear any pre-existing session and login the user
            self.request.session.clear()
            self.reset_user.emailaddress_set.filter(email=self.reset_user.email).update(verified=True)
            login(self.request, self.reset_user, backend="django.contrib.auth.backends.ModelBackend")
            return reverse("welcoming_tour:index")
        return super().get_success_url()

    def dispatch(self, request, uidb36, key, **kwargs):
        self.request = request
        self.key = key

        if self.key == self.reset_url_key:
            self.key = self.request.session.get(INTERNAL_RESET_SESSION_KEY, "")
            # (Ab)using forms here to be able to handle errors in XHR #890
            token_form = forms.UserTokenForm(data={"uidb36": uidb36, "key": self.key})
            if token_form.is_valid():
                self.reset_user = token_form.reset_user

                # In the event someone clicks on a password reset link
                # for one account while logged into another account,
                # logout of the currently logged in account.
                if self.request.user.is_authenticated and self.request.user.pk != self.reset_user.pk:
                    logout_with_message(self.request)
                    self.request.session[INTERNAL_RESET_SESSION_KEY] = self.key

                return super().dispatch(request, uidb36, self.key, **kwargs)
        else:
            token_form = forms.UserTokenForm(data={"uidb36": uidb36, "key": self.key})
            if token_form.is_valid():
                # Store the key in the session and redirect to the
                # password reset form at a URL without the key. That
                # avoids the possibility of leaking the key in the
                # HTTP Referer header.
                self.request.session[INTERNAL_RESET_SESSION_KEY] = self.key
                redirect_url = self.passthrough_next_url(self.request.path.replace(self.key, self.reset_url_key))
                return redirect(redirect_url)

        self.reset_user = None
        return self.render_to_response(self.get_context_data(token_fail=True))


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
