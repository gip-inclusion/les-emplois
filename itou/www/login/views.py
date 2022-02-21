from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.http import HttpResponsePermanentRedirect
from django.urls import reverse

from itou.utils.urls import get_safe_url
from itou.www.login.forms import ItouLoginForm


class ItouLoginView(LoginView):
    """
    Generic authentication entry point.
    It redirects to a more precise login view when a user type can be determined.
    """

    ACCOUNT_TYPE_TO_DISPLAY_NAME = {
        "prescriber": "Prescripteur",
        "siae": "Employeur solidaire",
        "institution": "Institution partenaire",
    }

    # The reverse() method cannot be used here as it causes
    # a cryptic loop import error in config/urls.py
    ACCOUNT_TYPE_TO_SIGNUP_URL = {
        "prescriber": "signup:prescriber_check_already_exists",
        "siae": "signup:siae_select",
    }

    form_class = ItouLoginForm
    template_name = "account/login_generic.html"

    def get_context_data(self, **kwargs):
        params = self.request.GET or self.request.POST
        account_type = params.get("account_type")
        signup_url = reverse(ItouLoginView.ACCOUNT_TYPE_TO_SIGNUP_URL.get(account_type, "account_signup"))
        show_france_connect = settings.FRANCE_CONNECT_ENABLED
        signup_allowed = account_type != "institution"
        redirect_field_value = get_safe_url(self.request, REDIRECT_FIELD_NAME)
        context = super().get_context_data(**kwargs)
        extra_context = {
            "account_type": account_type,
            "signup_url": signup_url,
            "show_france_connect": show_france_connect,
            "redirect_field_name": REDIRECT_FIELD_NAME,
            "redirect_field_value": redirect_field_value,
            "signup_allowed": signup_allowed,
        }
        return context | extra_context

    def redirect_to_login_type(self):
        """
        Historically, a generic login view was used to authenticate users.
        The "account_type" URL parameter mapped to the correct user type.
        We've split them into multiple classes but we should handle old urls.
        """
        account_type = self.request.GET.get("account_type") or self.request.POST.get("account_type")
        if account_type:
            if account_type == "siae":
                account_type = "siae_staff"
            if account_type not in ["siae_staff", "prescriber", "job_seeker", "labor_inspector"]:
                raise PermissionDenied
            return HttpResponsePermanentRedirect(reverse(f"login:{account_type}"))

    def get(self, *args, **kwargs):
        """
        If a user type cannot be found, display a generic form.
        This should never happen except in one case:
        when a user confirms its email after updating it.
        Allauth magic is complicated to debug.
        """
        redirection = self.redirect_to_login_type()
        if redirection:
            return redirection
        return super(ItouLoginView, self).get(*args, **kwargs)

    def post(self, *args, **kwargs):
        """
        If a user type cannot be found, display a generic form.
        This should never happen except in one case:
        when a user confirms its email after updating it.
        Allauth magic is complicated to debug.
        """
        redirection = self.redirect_to_login_type()
        if redirection:
            return redirection
        return super(ItouLoginView, self).post(*args, **kwargs)


class PrescriberLoginView(ItouLoginView):
    pass


class SiaeStaffLoginView(ItouLoginView):
    pass


class LaborInspectorLoginView(ItouLoginView):
    pass


class JobSeekerLoginView(ItouLoginView):
    template_name = "account/login_job_seeker.html"
