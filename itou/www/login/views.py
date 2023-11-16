from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.urls import reverse

from itou.users.enums import MATOMO_ACCOUNT_TYPE, UserKind
from itou.utils.urls import add_url_params, get_safe_url
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

        if self.user_kind in [UserKind.LABOR_INSPECTOR, UserKind.JOB_SEEKER]:
            return None

        params = {
            "user_kind": self.user_kind,
            "previous_url": self.request.get_full_path(),
        }
        if context["redirect_field_value"]:
            params["next_url"] = context["redirect_field_value"]

        return add_url_params(reverse("inclusion_connect:authorize"), params)

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
        }
        return context | extra_context


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
