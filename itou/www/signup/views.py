"""
Handle multiple user types sign up with django-allauth.
"""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from allauth.account.views import SignupView
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


def select_siae(request, template_name="signup/signup_select_siae.html"):
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
            f"Nous venons de vous envoyer un e-mail à l'adresse {siae.obfuscated_auth_email} "
            f"pour continuer votre inscription. Veuillez consulter votre boite "
            f"de réception."
        )
        messages.success(request, message)
        return HttpResponseRedirect(reverse("home:hp"))

    context = {"form": form}
    return render(request, template_name, context)


def redirect_to_select_siae_form(request):
    messages.warning(
        request, _("Ce lien d'inscription est invalide ou a expiré. " "Veuillez procéder à une nouvelle inscription.")
    )
    return HttpResponseRedirect(reverse("signup:select_siae"))


class SiaeSignupView(SignupView):

    form_class = forms.SiaeSignupForm
    template_name = "signup/signup_siae.html"

    def get(self, request, *args, **kwargs):
        form = forms.SiaeSignupForm(
            initial={"encoded_siae_id": kwargs.get("encoded_siae_id"), "token": kwargs.get("token")}
        )
        if form.check_siae_signup_credentials():
            self.initial = form.get_initial()
            return super().get(request, *args, **kwargs)
        return redirect_to_select_siae_form(request)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        form = forms.SiaeSignupForm(data=request.POST or None)
        if form.check_siae_signup_credentials():
            self.initial = form.get_initial()
            return super().post(request, *args, **kwargs)
        return redirect_to_select_siae_form(request)


class JobSeekerSignupView(SignupView):

    form_class = forms.JobSeekerSignupForm
    template_name = "signup/signup_job_seeker.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


def select_prescriber_type(request):
    """
    New signup process for prescribers, can be one of:
    * orienter
    * Pole Emploi prescriber
    * authorized prescriber
    """
    return render(request, "signup/signup_select_prescriber_type.html")


class OrienterPrescriberView(SignupView):
    template_name = "signup/signup_prescriber_orienter.html"
    form_class = forms.OrienterPrescriberForm


class PoleEmploiPrescriberView(SignupView):
    template_name = "signup/signup_prescriber_poleemploi.html"
    form_class = forms.PoleEmploiPrescriberForm


class AuthorizedPrescriberView(SignupView):
    template_name = "signup/signup_prescriber_authorized.html"
    form_class = forms.AuthorizedPrescriberForm
