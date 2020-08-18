"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import PasswordResetView, SignupView
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.decorators import method_decorator
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


def valid_prescriber_signup_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        if not session_data:
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


def prescriber_intro_step_pole_emploi(request, template_name="signup/prescriber_intro_step_pole_emploi.html"):
    """
    Entry point of the signup process for prescribers/orienteurs.

    80% of prescribers on Itou are Pôle emploi members: ask the user if this is the case.
    """

    # Start a fresh session.
    # It will be used through the multiple steps of the signup process.
    request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {
        "authorization_status": None,
        "kind": None,
        "prescriber_org_data": None,
        "prescriber_org_pk": None,
        "safir_code": None,
    }

    form = forms.PrescriberEntryPointForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        is_pole_emploi = form.cleaned_data["is_pole_emploi"]
        if is_pole_emploi:
            session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
            session_data["kind"] = PrescriberOrganization.Kind.PE.value
            return HttpResponseRedirect(reverse("signup:prescriber_pole_emploi_safir_code"))
        return HttpResponseRedirect(reverse("signup:prescriber_intro_step_org"))

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
def prescriber_intro_step_org(request, template_name="signup/prescriber_intro_step_org.html"):
    """
    Ask the user to choose the organization he's working for in a pre-existing list.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberIdentifyOrganizationKindForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        prescriber_kind = form.cleaned_data["kind"]

        if prescriber_kind == PrescriberOrganization.Kind.PE.value:
            session_data["kind"] = PrescriberOrganization.Kind.PE.value
            return HttpResponseRedirect(reverse("signup:prescriber_pole_emploi_safir_code"))

        if prescriber_kind == PrescriberOrganization.Kind.OTHER.value:
            session_data["kind"] = PrescriberOrganization.Kind.OTHER.value
            return HttpResponseRedirect(reverse("signup:prescriber_intro_step_kind"))

        session_data["kind"] = prescriber_kind
        return HttpResponseRedirect(reverse("signup:prescriber_intro_step_authorization"))

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
def prescriber_intro_step_kind(request, template_name="signup/prescriber_intro_step_kind.html"):
    """
    If the user hasn't found his organization, ask him other questions to identify his kind.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberIdentifyKindForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        prescriber_kind = form.cleaned_data["kind"]

        if prescriber_kind == form.KIND_AUTHORIZED_ORG:
            session_data["kind"] = PrescriberOrganization.Kind.OTHER.value
            return HttpResponseRedirect(reverse("signup:prescriber_intro_step_authorization"))

        if prescriber_kind == form.KIND_UNAUTHORIZED_ORG:
            session_data["kind"] = PrescriberOrganization.Kind.OTHER.value
            session_data["authorization_status"] = PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED.value
            return HttpResponseRedirect(reverse("signup:prescriber_siret"))

        # Go to sign up screen without organization.
        if prescriber_kind == form.KIND_SOLO:
            session_data["kind"] = None
            session_data["authorization_status"] = None
            return HttpResponseRedirect(reverse("signup:prescriber_user"))

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
def prescriber_intro_step_authorization(request, template_name="signup/prescriber_intro_step_authorization.html"):
    """
    Ask the user to confirm that his organization is authorized.

    That should help support with illegitimate or erroneous requests.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberConfirmAuthorizationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        confirm_authorization = form.cleaned_data["confirm_authorization"]
        if confirm_authorization:
            session_data["authorization_status"] = PrescriberOrganization.AuthorizationStatus.NOT_SET.value
            return HttpResponseRedirect(reverse("signup:prescriber_siret"))

        session_data["authorization_status"] = None
        return HttpResponseRedirect(reverse("signup:prescriber_intro_step_kind"))

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
def prescriber_pole_emploi_safir_code(request, template_name="signup/prescriber_pole_emploi_safir_code.html"):
    """
    Find a pre-existing Pôle emploi organization from a given SAFIR code.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberPoleEmploiSafirCodeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        session_data["prescriber_org_pk"] = form.prescriber_organization.pk
        session_data["safir_code"] = form.cleaned_data["safir_code"]
        return HttpResponseRedirect(reverse("signup:prescriber_pole_emploi_user"))

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
def prescriber_siret(request, template_name="signup/prescriber_siret.html"):
    """
    Get info about the prescriber's organization from a given SIRET.

    The SIRET is also the best way we have yet found to avoid duplicate organizations in the DB.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberSiretForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data["prescriber_org_data"] = form.org_data
        return HttpResponseRedirect(reverse("signup:prescriber_user"))

    context = {"form": form}
    return render(request, template_name, context)


class PrescriberPoleEmploiUserSignupView(SignupView):
    """
    Create a user of type prescriber and make him join a pre-existing Pôle emploi organization.
    """

    form_class = forms.PrescriberPoleEmploiUserSignupForm
    template_name = "signup/prescriber_pole_emploi_user.html"

    @transaction.atomic
    @method_decorator(valid_prescriber_signup_session_required)
    def dispatch(self, request, *args, **kwargs):

        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        kind = session_data.get("kind")
        prescriber_org_pk = session_data.get("prescriber_org_pk")

        # Check session data.
        if not prescriber_org_pk or kind != PrescriberOrganization.Kind.PE.value:
            raise PermissionDenied

        self.prescriber_organization = get_object_or_404(
            PrescriberOrganization, pk=prescriber_org_pk, kind=PrescriberOrganization.Kind.PE.value
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


class PrescriberUserSignupView(SignupView):
    """
    Create:

    - a user of type prescriber with an authorized organization
    - or: a user of type prescriber with an unauthorized organization ("orienteur")
    - or: a user of type prescriber without organization ("orienteur")

    If required, the "authorized" character of an organization is still to be validated
    by the support.
    """

    form_class = forms.PrescriberUserSignupForm
    template_name = "signup/prescriber_user.html"

    @transaction.atomic
    @method_decorator(valid_prescriber_signup_session_required)
    def dispatch(self, request, *args, **kwargs):

        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        authorization_status = session_data.get("authorization_status")
        prescriber_org_data = session_data.get("prescriber_org_data")
        kind = session_data.get("kind")

        join_as_orienteur_without_org = kind is None and authorization_status is None and prescriber_org_data is None

        join_as_orienteur_with_org = (
            authorization_status == PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED.value
            and kind == PrescriberOrganization.Kind.OTHER.value
            and prescriber_org_data is not None
        )

        join_authorized_org = (
            authorization_status == PrescriberOrganization.AuthorizationStatus.NOT_SET.value
            and kind not in [None, PrescriberOrganization.Kind.PE.value]
            and prescriber_org_data is not None
        )

        # Check session data. There can be only one kind.
        if sum([join_as_orienteur_without_org, join_as_orienteur_with_org, join_authorized_org]) != 1:
            raise PermissionDenied

        try:
            kind = PrescriberOrganization.Kind[kind]
        except KeyError:
            kind = None

        try:
            authorization_status = PrescriberOrganization.AuthorizationStatus[authorization_status]
        except KeyError:
            authorization_status = None

        self.authorization_status = authorization_status
        self.kind = kind
        self.prescriber_org_data = prescriber_org_data
        self.join_as_orienteur_without_org = join_as_orienteur_without_org
        self.join_authorized_org = join_authorized_org

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, **kwargs):
        kwargs = super().get_form_kwargs(**kwargs)
        kwargs.update(
            {
                "authorization_status": self.authorization_status,
                "kind": self.kind,
                "prescriber_org_data": self.prescriber_org_data,
            }
        )
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "join_as_orienteur_without_org": self.join_as_orienteur_without_org,
                "join_authorized_org": self.join_authorized_org,
                "kind": self.kind,
                "prescriber_org_data": self.prescriber_org_data,
            }
        )
        return context

    def form_valid(self, form):
        del self.request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        return super().form_valid(form)
