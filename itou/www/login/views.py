from urllib.parse import urlencode

from allauth.account.views import LoginView
from allauth.decorators import rate_limit
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView
from django_otp import login as otp_login

from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.users.enums import IDENTITY_PROVIDER_SUPPORTED_USER_KIND, MATOMO_ACCOUNT_TYPE, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.urls import get_safe_url, get_url_param_value
from itou.www.login.constants import ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY
from itou.www.login.forms import FindExistingUserViaEmailForm, ItouLoginForm, VerifyOTPForm


class UserKindLoginMixin:
    """
    Mixin class which adds functionality relating to the different IdentityProviders,
    configured to be used according to UserKind (certain identity providers accessible only to certain user kinds).
    django-allauth provides the login behaviour, extended by views for each UserKind.
    """

    form_class = ItouLoginForm
    user_kind = None

    # Allow users to choose their account type
    template_name = "account/account_type_selection.html"

    def _get_pro_connect_url(self, context):
        if not settings.PRO_CONNECT_BASE_URL:
            return None

        if self.user_kind not in IDENTITY_PROVIDER_SUPPORTED_USER_KIND[IdentityProvider.PRO_CONNECT]:
            return None

        params = {
            "user_kind": self.user_kind,
            "previous_url": self.request.get_full_path(),
        }
        if context["redirect_field_value"]:
            params["next_url"] = context["redirect_field_value"]

        return reverse("pro_connect:authorize", query=params)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "redirect_field_value": get_safe_url(self.request, REDIRECT_FIELD_NAME),
            "pro_connect_url": self._get_pro_connect_url(context),
        }
        return context | extra_context

    def dispatch(self, request, *args, **kwargs):
        if next_url := get_safe_url(request, "next"):
            if get_url_param_value(next_url, "channel") == ProConnectChannel.MAP_CONSEILLER:
                params = {
                    "user_kind": UserKind.PRESCRIBER,
                    "next_url": next_url,
                    "channel": ProConnectChannel.MAP_CONSEILLER.value,
                }
                return HttpResponseRedirect(f"{reverse('pro_connect:authorize')}?{urlencode(params)}")
        return super().dispatch(request, *args, **kwargs)


class ItouLoginView(LoginNotRequiredMixin, UserKindLoginMixin, LoginView):
    """Generic authentication entry point."""

    pass


class PrescriberLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.PRESCRIBER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        extra_context = {
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.PRESCRIBER],
            "uses_pro_connect": True,
        }
        return context | extra_context


class EmployerLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.EMPLOYER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        extra_context = {
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.EMPLOYER],
            "uses_pro_connect": True,
        }
        return context | extra_context


class LaborInspectorLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.LABOR_INSPECTOR

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "uses_pro_connect": False,
        }
        return context | extra_context


class JobSeekerPreLoginView(LoginNotRequiredMixin, UserKindLoginMixin, FormView):
    """
    JobSeeker's do not log in directly.
    Instead they enter their email and they are redirected to the login method configured on their account.
    """

    template_name = "account/login_job_seeker.html"
    user_kind = UserKind.JOB_SEEKER
    form_class = FindExistingUserViaEmailForm

    @method_decorator(rate_limit(action="login"))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        self.user = form.user
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('login:existing_user', args=(self.user.public_id,))}?back_url={reverse('login:job_seeker')}"


class ExistingUserLoginView(ItouLoginView):
    """
    Allows a user to login with the provider configured on their account.
    """

    template_name = "account/login_existing_user.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user = get_object_or_404(User, public_id=self.kwargs["user_public_id"])
        self.user_kind = self.user.kind

    def get_user_email(self):
        """
        This template can optionally have the email of the user displayed, if it is safe to do so.
        This is done using the session and comparing the stashed value to the user concerned by this view.
        """
        stashed_email = self.request.session.get(ITOU_SESSION_JOB_SEEKER_LOGIN_EMAIL_KEY, None)
        return stashed_email if stashed_email == self.user.email else None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user_email"] = self.get_user_email()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "back_url": get_safe_url(self.request, "back_url"),
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[self.user.kind]
            if self.user.kind in MATOMO_ACCOUNT_TYPE
            else self.user.kind,
            "login_provider": self.user.identity_provider,
            "show_france_connect": bool(settings.FRANCE_CONNECT_BASE_URL),
            "show_peamu": bool(settings.PEAMU_AUTH_BASE_URL),
        }
        return context | extra_context


class ItouStaffLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.ITOU_STAFF

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context | {"uses_pro_connect": False}


class VerifyOTPView(FormView):
    template_name = "account/verify_otp.html"
    form_class = VerifyOTPForm

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"user": self.request.user}

    def form_valid(self, form):
        otp_login(self.request, self.request.user.otp_device)
        return super().form_valid(form)

    def get_success_url(self):
        return get_safe_url(self.request, REDIRECT_FIELD_NAME, reverse("dashboard:index"))
