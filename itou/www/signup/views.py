"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import SignupView

from django.db import transaction
from django.shortcuts import render
from django.views.decorators.http import require_GET

from itou.utils.urls import get_safe_url
from itou.www.signup import forms


@require_GET
def signup(request, template_name="signup/signup.html", redirect_field_name="next"):
    """
    Override allauth `account_signup` URL
    (the route is defined in config.urls).
    """
    context = {
        "redirect_field_name": redirect_field_name,
        "redirect_field_value": get_safe_url(request, redirect_field_name),
    }
    return render(request, template_name, context)


class PrescriberSignupView(SignupView):

    form_class = forms.PrescriberSignupForm
    template_name = "signup/signup_prescriber.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


class SiaeSignupView(SignupView):

    form_class = forms.SiaeSignupForm
    template_name = "signup/signup_siae.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


class JobSeekerSignupView(SignupView):

    form_class = forms.JobSeekerSignupForm
    template_name = "signup/signup_job_seeker.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)
