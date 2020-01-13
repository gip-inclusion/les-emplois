"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import SignupView

from django.db import transaction
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from itou.users.models import User, UserValidation
from itou.utils.urls import get_safe_url
from itou.www.signup import forms


@require_GET
def account_inactive(request, user_uuid, template_name="signup/account_inactive.html"):
    """
    Custom account_inactive view which preserves user info, unlike the default allauth one.
    """
    context = {"user": User.objects.get(uuid=user_uuid)}
    return render(request, template_name, context=context)


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


@require_GET
def validation(request, user_uuid, secret, template_name="signup/validation.html"):
    """
    Validate a pending new user signup by making the user active.
    """
    query = UserValidation.objects.filter(user__uuid=user_uuid, secret=secret)
    if not query.exists():
        message = _("Ce lien d'activation est incorrect ou n'est plus valide.")
        return render(request, template_name, context={"message": message})

    user_validation = query.get()
    if user_validation.is_validated:
        message = _(
            f"Ce lien d'activation du compte {user_validation.user.email} a déjà été utilisé."
        )
    else:
        user_validation.complete()
        message = _(
            f"L'utilisateur {user_validation.user.email} a bien été validé "
            f"et peut maintenant s'identifier sur la plateforme."
        )
    return render(request, template_name, context={"message": message})


@require_GET
def delete_account_pending_validation(
    request, user_uuid, template_name="signup/delete_account_pending_validation.html"
):
    """
    FIXME
    """
    pass
