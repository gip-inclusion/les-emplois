from allauth.account.views import LoginView
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.template.response import TemplateResponse
from django.urls import reverse

from itou.utils.urls import get_safe_url


class ItouLoginView(LoginView):

    ACCOUNT_TYPE_TO_DISPLAY_NAME = {
        "job_seeker": "Candidat",
        "prescriber": "Prescripteur",
        "siae": "Employeur solidaire",
    }

    # The reverse() method cannot be used here as it causes
    # a cryptic loop import error in config/urls.py
    ACCOUNT_TYPE_TO_SIGNUP_URL = {
        "job_seeker": "signup:job_seeker",
        "prescriber": "signup:prescriber_is_pole_emploi",
        "siae": "signup:siae_select",
    }

    template_name = "account/login.html"

    def inject_context_into_response(self, response, params):
        if isinstance(response, TemplateResponse):
            account_type = params.get("account_type")
            account_type_display_name = ItouLoginView.ACCOUNT_TYPE_TO_DISPLAY_NAME.get(account_type)
            signup_url = reverse(ItouLoginView.ACCOUNT_TYPE_TO_SIGNUP_URL.get(account_type, "account_signup"))
            show_peamu = account_type == "job_seeker"
            redirect_field_value = get_safe_url(self.request, REDIRECT_FIELD_NAME)

            context = {
                "account_type": account_type,
                "account_type_display_name": account_type_display_name,
                "signup_url": signup_url,
                "show_peamu": show_peamu,
                "redirect_field_name": REDIRECT_FIELD_NAME,
                "redirect_field_value": redirect_field_value,
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


login = ItouLoginView.as_view()
