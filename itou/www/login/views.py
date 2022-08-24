from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.urls import reverse
from django.utils.http import urlencode

from itou.users.enums import KIND_PRESCRIBER
from itou.utils.urls import get_safe_url
from itou.www.login.forms import ItouLoginForm


class ItouLoginView(LoginView):
    """
    Generic authentication entry point.
    This view is used only in one case:
    when a user confirms its email after updating it.
    Allauth magic is complicated to debug.
    """

    form_class = ItouLoginForm

    # Allow users to choose their account type
    template_name = "account/account_type_selection.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        login_url = reverse("account_login")
        signup_url = reverse("account_signup")
        extra_context = {
            "login_url": login_url,
            "signup_url": signup_url,
            "signup_allowed": True,
            "redirect_field_name": REDIRECT_FIELD_NAME,
            "redirect_field_value": get_safe_url(self.request, REDIRECT_FIELD_NAME),
        }
        return context | extra_context


class PrescriberLoginView(ItouLoginView):
    template_name = "account/login_generic.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": self.request.resolver_match.view_name,
        }
        inclusion_connect_url = f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}"
        extra_context = {
            "account_type_display_name": "prescripteur",
            "login_url": reverse("login:prescriber"),
            "signup_url": reverse("signup:prescriber_check_already_exists"),
            "signup_allowed": True,
            "inclusion_connect_url": inclusion_connect_url,
        }
        return context | extra_context


class SiaeStaffLoginView(ItouLoginView):
    template_name = "account/login_generic.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "account_type_display_name": "employeur solidaire",
            "login_url": reverse("login:siae_staff"),
            "signup_url": reverse("signup:siae_select"),
            "signup_allowed": True,
        }
        return context | extra_context


class LaborInspectorLoginView(ItouLoginView):
    template_name = "account/login_generic.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "account_type_display_name": "institution partenaire",
            "login_url": reverse("login:labor_inspector"),
            "signup_allowed": False,
        }
        return context | extra_context


class JobSeekerLoginView(ItouLoginView):
    template_name = "account/login_job_seeker.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        show_france_connect = settings.FRANCE_CONNECT_ENABLED
        show_peamu = settings.PEAMU_ENABLED
        extra_context = {
            "show_france_connect": show_france_connect,
            "show_peamu": show_peamu,
        }
        return context | extra_context
