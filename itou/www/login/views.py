from allauth.account.views import LoginView
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import reverse

from itou.utils.urls import get_safe_url
from itou.www.login.forms import ItouLoginForm


def permission_denied(request):
    # AllAuth default login page should never be accessed alone.
    raise PermissionDenied


class ItouLoginView(LoginView):
    ACCOUNT_TYPE_TO_DISPLAY_NAME = {
        "job_seeker": "Candidat",
        "prescriber": "Prescripteur",
        "siae": "Employeur solidaire",
        "institution": "Institution partenaire",
    }

    # The reverse() method cannot be used here as it causes
    # a cryptic loop import error in config/urls.py
    ACCOUNT_TYPE_TO_SIGNUP_URL = {
        "job_seeker": "signup:job_seeker_situation",
        "prescriber": "signup:prescriber_check_already_exists",
        "siae": "signup:siae_select",
    }

    form_class = ItouLoginForm
    template_name = "account/login.html"

    def inject_context_into_response(self, response, params):
        if isinstance(response, TemplateResponse):
            account_type = params.get("account_type")
            signup_url = reverse(ItouLoginView.ACCOUNT_TYPE_TO_SIGNUP_URL.get(account_type, "account_signup"))
            show_sign_in_providers = account_type == "job_seeker"
            show_france_connect = settings.FRANCE_CONNECT_ENABLED
            signup_allowed = account_type != "institution"
            redirect_field_value = get_safe_url(self.request, REDIRECT_FIELD_NAME)

            context = {
                "account_type": account_type,
                "signup_url": signup_url,
                "show_sign_in_providers": show_sign_in_providers,
                "show_france_connect": show_france_connect,
                "redirect_field_name": REDIRECT_FIELD_NAME,
                "redirect_field_value": redirect_field_value,
                "signup_allowed": signup_allowed,
            }
            response.context_data.update(context)

        return response

    def get(self, *args, **kwargs):
        response = super(ItouLoginView, self).get(*args, **kwargs)
        response = self.inject_context_into_response(response, params=self.request.GET)
        return response

    def post(self, *args, **kwargs):
        response = super(ItouLoginView, self).post(*args, **kwargs)
        response = self.inject_context_into_response(response, params=self.request.POST)
        return response
