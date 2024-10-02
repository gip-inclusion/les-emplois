from urllib.parse import urlencode

from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse

from itou.openid_connect.inclusion_connect.enums import InclusionConnectChannel
from itou.users.enums import MATOMO_ACCOUNT_TYPE, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.urls import add_url_params, get_safe_url, get_url_param_value
from itou.www.login.forms import ItouLoginForm


class ItouLoginView(LoginView):
    """
    Generic authentication entry point.
    This view is used only in one case:
    when a user confirms its email after updating it.
    Allauth magic is complicated to debug.
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


class JobSeekerLoginView(ItouLoginView):
    template_name = "account/login_job_seeker.html"
    user_kind = UserKind.JOB_SEEKER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "show_france_connect": bool(settings.FRANCE_CONNECT_BASE_URL),
            "show_peamu": bool(settings.PEAMU_AUTH_BASE_URL),
        }
        return context | extra_context


class ExistingUserLoginView(ItouLoginView):
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
