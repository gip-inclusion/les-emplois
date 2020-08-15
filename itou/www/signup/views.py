"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import PasswordResetView, SignupView
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from itou.prescribers.models import PrescriberOrganization
from itou.utils.urls import get_safe_url
from itou.www.signup import forms


class ItouPasswordResetView(PasswordResetView):
    def form_invalid(self, form):
        """
        Avoid user enumeration: django-allauth displays an error message to the user
        when an email does not exist. We deliberately hide it by redirecting to the
        success page in all cases.
        """
        return HttpResponseRedirect(self.get_success_url())


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
            message = _(
                "Cette structure a déjà des membres. Pour des raisons de sécurité, "
                "merci de contacter les autres membres afin qu'ils vous invitent."
            )
            messages.warning(request, message)
        else:
            siae.new_signup_activation_email_to_official_contact(request).send()
            message = _(
                f"Nous venons de vous envoyer un e-mail à l'adresse {siae.obfuscated_auth_email} "
                f"pour continuer votre inscription. Veuillez consulter votre boite "
                f"de réception."
            )
            messages.success(request, message)
        return HttpResponseRedirect("/")

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


# OLD


def select_prescriber_type(request):
    """
    New signup process for prescribers, can be one of:
    * orienter
    * Pole Emploi prescriber
    * authorized prescriber
    """
    return render(request, "signup/signup_select_prescriber_type.html")


class PrescriberSignup(SignupView):
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


class OrienterPrescriberView(PrescriberSignup):
    template_name = "signup/signup_prescriber_orienter.html"
    form_class = forms.OrienterPrescriberForm


class PoleEmploiPrescriberView(PrescriberSignup):
    template_name = "signup/signup_prescriber_poleemploi.html"
    form_class = forms.PoleEmploiPrescriberForm


class AuthorizedPrescriberView(PrescriberSignup):
    template_name = "signup/signup_prescriber_authorized.html"
    form_class = forms.AuthorizedPrescriberForm


# TODO: NEW
# ------------------------------------------------------------------------------------------


def prescriber_entry_point(request, template_name="signup/prescriber_entry_point.html"):
    """
    Entry point of the signup process for prescribers/orienters.

    Since 80% of prescribers who sign up on Itou are Pôle emploi members,
    we get them into the right funnel as soon as possible.
    """

    # Start a fresh session. It will be used through the multiple steps of the signup process.
    request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {
        "kind": None,
        "prescriber_organization_pk": None,
    }

    form = forms.PrescriberEntryPointForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        is_pole_emploi = form.cleaned_data["is_pole_emploi"]
        if is_pole_emploi:
            return HttpResponseRedirect(reverse("signup:prescriber_pole_emploi_safir_code"))
        else:
            pass
            # TODO: redirect to other signups

    context = {"form": form}
    return render(request, template_name, context)


def prescriber_pole_emploi_safir_code(request, template_name="signup/prescriber_pole_emploi_safir_code.html"):

    form = forms.PrescriberPoleEmploiSafirCodeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        session_data["kind"] = PrescriberOrganization.Kind.PE.value
        session_data["prescriber_organization_pk"] = form.prescriber_organization.pk
        return HttpResponseRedirect(reverse("signup:prescriber_pole_emploi_user"))

    context = {"form": form}
    return render(request, template_name, context)


class PrescriberPoleEmploiUserSignupView(SignupView):

    form_class = forms.PrescriberPoleEmploiUserSignupForm
    template_name = "signup/prescriber_pole_emploi_user.html"

    def __init__(self, **kwargs):
        self.prescriber_organization = None
        return super().__init__(**kwargs)

    @transaction.atomic
    def dispatch(self, request, *args, **kwargs):

        session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        if not session_data:
            raise Http404()

        kind = session_data.get("kind")
        prescriber_organization_pk = session_data.get("prescriber_organization_pk")
        if (kind != PrescriberOrganization.Kind.PE.value) or not prescriber_organization_pk:
            raise Http404()

        self.prescriber_organization = get_object_or_404(
            PrescriberOrganization, pk=prescriber_organization_pk, kind=PrescriberOrganization.Kind.PE.value
        )

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, **kwargs):
        kwargs = super().get_form_kwargs(**kwargs)
        # Pass the PrescriberOrganization instance to the form.
        kwargs["prescriber_organization"] = self.prescriber_organization
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["prescriber_organization"] = self.prescriber_organization
        return context

    def form_valid(self, form):
        del self.request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        return super().form_valid(form)
