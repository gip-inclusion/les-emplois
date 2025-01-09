from urllib.parse import urlencode

from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic.edit import FormView

from itou.openid_connect.inclusion_connect.enums import InclusionConnectChannel
from itou.users.enums import MATOMO_ACCOUNT_TYPE, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.urls import add_url_params, get_safe_url, get_url_param_value
from itou.www.login.forms import FindExistingUserViaEmailForm, ItouLoginForm


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

    def _get_inclusion_connect_url(self, context):
        if not settings.INCLUSION_CONNECT_BASE_URL:
            return None

        if self.user_kind not in IdentityProvider.supported_user_kinds[IdentityProvider.INCLUSION_CONNECT]:
            return None

        params = {
            "user_kind": self.user_kind,
            "previous_url": self.request.get_full_path(),
        }
        if context["redirect_field_value"]:
            params["next_url"] = context["redirect_field_value"]

        return add_url_params(reverse("inclusion_connect:authorize"), params)

    def _get_pro_connect_url(self, context):
        if not settings.PRO_CONNECT_BASE_URL:
            return None

        if self.user_kind not in IdentityProvider.supported_user_kinds[IdentityProvider.PRO_CONNECT]:
            return None

        params = {
            "user_kind": self.user_kind,
            "previous_url": self.request.get_full_path(),
        }
        if context["redirect_field_value"]:
            params["next_url"] = context["redirect_field_value"]

        return add_url_params(reverse("pro_connect:authorize"), params)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        login_url = reverse("account_login")
        signup_url = reverse("account_signup")
        extra_context = {
            "login_url": login_url,
            "signup_url": signup_url,
            "signup_allowed": True,
            "redirect_field_value": get_safe_url(self.request, REDIRECT_FIELD_NAME),
            "inclusion_connect_url": self._get_inclusion_connect_url(context),
            "pro_connect_url": self._get_pro_connect_url(context),
        }
        return context | extra_context

    def dispatch(self, request, *args, **kwargs):
        if next_url := request.GET.get("next"):
            if get_url_param_value(next_url, "channel") == InclusionConnectChannel.MAP_CONSEILLER:
                params = {
                    "user_kind": UserKind.PRESCRIBER,
                    "next_url": next_url,
                    "channel": InclusionConnectChannel.MAP_CONSEILLER.value,
                }
                if settings.PRO_CONNECT_BASE_URL:
                    redirect_to = f"{reverse('pro_connect:authorize')}?{urlencode(params)}"
                else:
                    redirect_to = f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}"
                return HttpResponseRedirect(redirect_to)
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
            "login_url": reverse("login:prescriber"),
            "signup_url": reverse("signup:prescriber_check_already_exists"),
            "signup_allowed": True,
            "uses_inclusion_connect": True,
        }
        return context | extra_context


class EmployerLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.EMPLOYER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        extra_context = {
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.EMPLOYER],
            "login_url": reverse("login:employer"),
            "signup_url": reverse("signup:company_select"),
            "signup_allowed": True,
            "uses_inclusion_connect": True,
        }
        return context | extra_context


class LaborInspectorLoginView(ItouLoginView):
    template_name = "account/login_generic.html"
    user_kind = UserKind.LABOR_INSPECTOR

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "login_url": reverse("login:labor_inspector"),
            "signup_allowed": False,
            "uses_inclusion_connect": False,
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
