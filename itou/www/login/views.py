from allauth.account.views import LoginView
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


class ItouLoginView(LoginView):

    ACCOUNT_TYPE_TO_DISPLAY_NAME = {
        "job_seeker": _("Candidat"),
        "prescriber": _("Prescripteur"),
        "siae": _("Employeur solidaire"),
    }

    # The reverse() method cannot be used here as it causes
    # a cryptic loop import error in config/urls.py
    ACCOUNT_TYPE_TO_SIGNUP_URL = {
        "job_seeker": "signup:job_seeker",
        "prescriber": "signup:prescriber_is_pole_emploi",
        "siae": "signup:select_siae",
    }

    template_name = "account/login.html"

    def inject_context_into_response(self, response, params):
        if isinstance(response, TemplateResponse):
            account_type = params.get("account_type")
            account_type_display_name = ItouLoginView.ACCOUNT_TYPE_TO_DISPLAY_NAME.get(account_type)
            signup_url = reverse(ItouLoginView.ACCOUNT_TYPE_TO_SIGNUP_URL.get(account_type, "account_signup"))
            response.context_data["account_type"] = account_type
            response.context_data["account_type_display_name"] = account_type_display_name
            response.context_data["signup_url"] = signup_url
            response.context_data["show_peamu"] = account_type == "job_seeker"
        return response

    def get(self, *args, **kwargs):
        response = super(ItouLoginView, self).get(*args, **kwargs)
        response = self.inject_context_into_response(response, params=self.request.GET)
        return response

    def post(self, *args, **kwargs):
        response = super(ItouLoginView, self).post(*args, **kwargs)
        response = self.inject_context_into_response(response, params=self.request.POST)
        return response


login = ItouLoginView.as_view()
