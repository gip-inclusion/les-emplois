from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import FormView

from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.urls import add_url_params, get_safe_url
from itou.www.login.forms import AccountMigrationForm, ItouLoginForm


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

        ic_base_url = reverse("login:activate_prescriber_account")

        if context["redirect_field_value"] is not None:
            ic_base_url = add_url_params(ic_base_url, {REDIRECT_FIELD_NAME: context["redirect_field_value"]})

        extra_context = {
            "account_type_display_name": "prescripteur",
            "matomo_account_type": UserKind.PRESCRIBER,
            "login_url": reverse("login:prescriber"),
            "signup_url": reverse("signup:prescriber_check_already_exists"),
            "signup_allowed": True,
            "uses_inclusion_connect": True,
            "inclusion_connect_url": f"{ic_base_url}",
        }
        return context | extra_context


class SiaeStaffLoginView(ItouLoginView):
    template_name = "account/login_generic.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        ic_base_url = reverse("login:activate_siae_staff_account")

        if context["redirect_field_value"] is not None:
            ic_base_url = add_url_params(ic_base_url, {REDIRECT_FIELD_NAME: context["redirect_field_value"]})

        extra_context = {
            "account_type_display_name": "employeur solidaire",
            "matomo_account_type": UserKind.SIAE_STAFF,
            "login_url": reverse("login:siae_staff"),
            "signup_url": reverse("signup:siae_select"),
            "signup_allowed": True,
            "uses_inclusion_connect": True,
            "inclusion_connect_url": f"{ic_base_url}",
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
        extra_context = {
            "show_france_connect": bool(settings.FRANCE_CONNECT_BASE_URL),
            "show_peamu": bool(settings.PEAMU_AUTH_BASE_URL),
        }
        return context | extra_context


class AccountMigrationBaseView(FormView):
    template_name = "account/activate_inclusion_connect_account.html"
    form_class = AccountMigrationForm

    def _get_inclusion_connect_base_params(self):
        params = {"user_kind": self.user_kind, "previous_url": self.request.get_full_path()}

        next = get_safe_url(self.request, REDIRECT_FIELD_NAME)

        if next:
            params["next_url"] = next

        return params

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self._get_inclusion_connect_base_params()
        existing_ic_account = self.request.GET.get("existing_ic_account")
        inclusion_connect_url = add_url_params(reverse("inclusion_connect:authorize"), params)
        existing_ic_account_url = None
        if existing_ic_account:
            params["user_email"] = existing_ic_account
            existing_ic_account_url = add_url_params(reverse("inclusion_connect:authorize"), params)

        extra_context = {
            "inclusion_connect_url": inclusion_connect_url,
            "existing_ic_account": existing_ic_account,
            "existing_ic_account_url": existing_ic_account_url,
            "matomo_account_type": self.user_kind,
        }

        return context | extra_context

    def form_valid(self, form):
        self.form = form
        email = self.form.cleaned_data["email"]
        if User.objects.filter(
            email=email, kind=self.user_kind, identity_provider=IdentityProvider.INCLUSION_CONNECT
        ).exists():
            params = {"existing_ic_account": email}
            return HttpResponseRedirect(add_url_params(self.request.get_full_path(), params))
        return super().form_valid(form)

    def get_success_url(self):
        params = self._get_inclusion_connect_base_params()
        params["user_email"] = self.form.cleaned_data["email"]
        return add_url_params(reverse("inclusion_connect:activate_account"), params)


class PrescriberAccountMigrationView(AccountMigrationBaseView):
    url_name = "login:activate_prescriber_account"
    user_kind = UserKind.PRESCRIBER


class SiaeStaffAccountMigrationView(AccountMigrationBaseView):
    url_name = "login:activate_siae_staff_account"
    user_kind = UserKind.SIAE_STAFF
