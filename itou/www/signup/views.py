"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import SignupView

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from itou.utils.urls import get_safe_url
from itou.www.signup import forms, utils


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


def select_siae(request, template_name="signup/select_siae.html"):
    """
    Select an existing SIAE (Agence / Etablissement in French) to join.
    This is the first of the two forms of the siae signup process.
    """
    form = forms.SelectSiaeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        siae = form.selected_siae

        if siae.has_members:
            return HttpResponseRedirect(siae.signup_magic_link)

        siae.new_signup_activation_email_to_official_contact(request).send()
        message = _(
            f"Nous venons de vous envoyer un e-mail à l'adresse {siae.auth_email} "
            f"pour continuer votre inscription. Veuillez consulter votre boite "
            f"de réception."
        )
        messages.success(request, message)
        return HttpResponseRedirect(reverse("home:hp"))

    context = {"form": form, "itou_email_contact": settings.ITOU_EMAIL_CONTACT}
    return render(request, template_name, context)


def redirect_to_select_siae_form(request):
    messages.warning(
        request,
        _(
            "Ce lien d'inscription est invalide ou a expiré. "
            "Veuillez procéder à une nouvelle inscription."
        ),
    )
    return HttpResponseRedirect(reverse("signup:select_siae"))


class SiaeSignupView(SignupView):

    form_class = forms.SiaeSignupForm
    template_name = "signup/signup_siae.html"

    def get(self, request, *args, **kwargs):
        request.session[settings.ITOU_SESSION_SIAE_SIGNUP_ID] = kwargs.get(
            "encoded_siae_id"
        )
        request.session[settings.ITOU_SESSION_SIAE_SIGNUP_TOKEN] = kwargs.get("token")
        if utils.check_siae_signup_credentials(request.session):
            self.initial = get_initial_from_session(request.session)
            return super().get(request, *args, **kwargs)
        return redirect_to_select_siae_form(request)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        if utils.check_siae_signup_credentials(request.session):
            self.initial = get_initial_from_session(request.session)
            return super().post(request, *args, **kwargs)
        return redirect_to_select_siae_form(request)


def get_initial_from_session(session):
    siae = utils.get_siae_from_session(session)
    return {"siret": siae.siret, "kind": siae.kind, "siae_name": siae.display_name}


class JobSeekerSignupView(SignupView):

    form_class = forms.JobSeekerSignupForm
    template_name = "signup/signup_job_seeker.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)
