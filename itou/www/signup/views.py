"""
Handle multiple user types sign up with django-allauth.
"""
from allauth.account.views import PasswordResetView, SignupView
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.nav_history import get_prev_url_from_history, push_url_in_history
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
def signup(request, template_name="signup/signup.html", redirect_field_name=REDIRECT_FIELD_NAME):
    """
    Override allauth `account_signup` URL
    (the route is defined in config.urls).
    """
    context = {
        "redirect_field_name": redirect_field_name,
        "redirect_field_value": get_safe_url(request, redirect_field_name),
    }
    return render(request, template_name, context)


class JobSeekerSignupView(SignupView):

    form_class = forms.JobSeekerSignupForm
    template_name = "signup/job_seeker_signup.html"

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


# SIAEs signup.
# ------------------------------------------------------------------------------------------


def siae_select(request, template_name="signup/siae_select.html"):
    """
    Entry point of the signup process for SIAEs which consists of 2 steps.

    The user is asked to select an SIAE based on a selection that match a given SIREN number.
    """

    siaes_without_members = None
    siaes_with_members = None

    next_url = get_safe_url(request, "next")

    siren_form = forms.SiaeSearchBySirenForm(data=request.GET or None)
    siae_select_form = None

    # The SIREN, when available, is always passed in the querystring.
    if request.method in ["GET", "POST"] and siren_form.is_valid():
        # Make sure to look only for active structures.
        siaes_for_siren = Siae.objects.active().filter(siret__startswith=siren_form.cleaned_data["siren"])
        # A user cannot join structures that already have members.
        # Show these structures in the template to make that clear.
        siaes_with_members = siaes_for_siren.exclude(members=None)
        siaes_without_members = siaes_for_siren.filter(members=None)
        siae_select_form = forms.SiaeSelectForm(data=request.POST or None, siaes=siaes_without_members)

    if request.method == "POST" and siae_select_form and siae_select_form.is_valid():
        siae_selected = siae_select_form.cleaned_data["siaes"]
        siae_selected.new_signup_activation_email_to_official_contact(request).send()
        message = _(
            f"Nous venons d'envoyer un e-mail à l'adresse {siae_selected.obfuscated_auth_email} "
            f"pour continuer votre inscription. Veuillez consulter votre boite "
            f"de réception."
        )
        messages.success(request, message)
        return HttpResponseRedirect(next_url or "/")

    context = {
        "DOC_OPENING_SCHEDULE_URL": settings.ITOU_DOC_OPENING_SCHEDULE_URL,
        "typeform_link": settings.ITOU_CHECK_SIRET_LINK,
        "next_url": next_url,
        "siaes_without_members": siaes_without_members,
        "siaes_with_members": siaes_with_members,
        "siae_select_form": siae_select_form,
        "siren_form": siren_form,
    }
    return render(request, template_name, context)


class SiaeSignupView(SignupView):

    form_class = forms.SiaeSignupForm
    template_name = "signup/siae_signup.html"

    def warn_and_redirect(self, request):
        messages.warning(
            request, _("Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.")
        )
        return HttpResponseRedirect(reverse("signup:siae_select"))

    def get(self, request, *args, **kwargs):
        form = forms.SiaeSignupForm(
            initial={"encoded_siae_id": kwargs.get("encoded_siae_id"), "token": kwargs.get("token")}
        )
        if form.check_siae_signup_credentials():
            self.initial = form.get_initial()
            return super().get(request, *args, **kwargs)
        return self.warn_and_redirect(request)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        form = forms.SiaeSignupForm(data=request.POST or None)
        if form.check_siae_signup_credentials():
            self.initial = form.get_initial()
            return super().post(request, *args, **kwargs)
        return self.warn_and_redirect(request)


# Prescribers signup.
# ------------------------------------------------------------------------------------------


def valid_prescriber_signup_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        if not session_data:
            # Someone tries to use the direct link of a step inside the process
            # without going through the beginning.
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


def prescriber_is_pole_emploi(request, template_name="signup/prescriber_is_pole_emploi.html"):
    """
    Entry point of the signup process for prescribers/orienteurs.

    The signup process consists of several steps during which the user answers
    a series of questions to determine the `kind` of his organization if any.

    Answers are kept in session.

    At the end of the process a user will be created and he will be:
    - added to the members of a pre-existing Pôle emploi agency ("prescripteur habilité")
    - added to the members of a new authorized organization ("prescripteur habilité")
    - added to the members of a new unauthorized organization ("orienteur")
    - without any organization ("orienteur")

    Step 1: as 80% of prescribers on Itou are Pôle emploi members,
    ask the user if he works for PE.
    """

    # Start a fresh session that will be used during the signup process.
    # Since we can go back-and-forth, or someone always has the option
    # of using a direct link, its state must be kept clean in each step.
    request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {
        "authorization_status": None,
        "kind": None,
        "prescriber_org_data": None,
        "pole_emploi_org_pk": None,
        "safir_code": None,
        "url_history": [request.path],
        "next": get_safe_url(request, "next"),
    }

    form = forms.PrescriberIsPoleEmploiForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        next_url = reverse("signup:prescriber_choose_org")

        if form.cleaned_data["is_pole_emploi"]:
            next_url = reverse("signup:prescriber_pole_emploi_safir_code")

        return HttpResponseRedirect(next_url)

    context = {"form": form}
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_choose_org(request, template_name="signup/prescriber_choose_org.html"):
    """
    Ask the user to choose his organization in a pre-existing list of authorized organization.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberChooseOrgKindForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        prescriber_kind = form.cleaned_data["kind"]
        authorization_status = None

        if prescriber_kind == PrescriberOrganization.Kind.PE.value:
            next_url = reverse("signup:prescriber_pole_emploi_safir_code")

        elif prescriber_kind == PrescriberOrganization.Kind.OTHER.value:
            next_url = reverse("signup:prescriber_choose_kind")

        else:
            # A pre-existing kind of authorized organization was chosen.
            authorization_status = PrescriberOrganization.AuthorizationStatus.NOT_SET.value
            next_url = reverse("signup:prescriber_siret")

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": prescriber_kind,
                "prescriber_org_data": None,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_choose_kind(request, template_name="signup/prescriber_choose_kind.html"):
    """
    If the user hasn't found his organization in the pre-existing list, ask him to choose his kind.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberChooseKindForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        prescriber_kind = form.cleaned_data["kind"]
        authorization_status = None
        kind = None

        if prescriber_kind == form.KIND_AUTHORIZED_ORG:
            next_url = reverse("signup:prescriber_confirm_authorization")

        elif prescriber_kind == form.KIND_UNAUTHORIZED_ORG:
            authorization_status = PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED.value
            kind = PrescriberOrganization.Kind.OTHER.value
            next_url = reverse("signup:prescriber_siret")

        elif prescriber_kind == form.KIND_SOLO:
            # Go to sign up screen without organization.
            next_url = reverse("signup:prescriber_user")

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": kind,
                "prescriber_org_data": None,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_confirm_authorization(request, template_name="signup/prescriber_confirm_authorization.html"):
    """
    Ask the user to confirm the "authorized" character of his organization.

    That should help the support team with illegitimate or erroneous requests.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberConfirmAuthorizationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        authorization_status = "NOT_SET" if form.cleaned_data["confirm_authorization"] else "NOT_REQUIRED"
        session_data.update(
            {
                "authorization_status": PrescriberOrganization.AuthorizationStatus[authorization_status].value,
                "kind": PrescriberOrganization.Kind.OTHER.value,
                "prescriber_org_data": None,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        next_url = reverse("signup:prescriber_siret")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_pole_emploi_safir_code(request, template_name="signup/prescriber_pole_emploi_safir_code.html"):
    """
    Find a pre-existing Pôle emploi organization from a given SAFIR code.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberPoleEmploiSafirCodeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data.update(
            {
                "authorization_status": None,
                "kind": PrescriberOrganization.Kind.PE.value,
                "prescriber_org_data": None,
                "pole_emploi_org_pk": form.pole_emploi_org.pk,
                "safir_code": form.cleaned_data["safir_code"],
            }
        )
        next_url = reverse("signup:prescriber_pole_emploi_user")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_siret(request, template_name="signup/prescriber_siret.html"):
    """
    Automatically fetch info about the prescriber's organization from a given SIRET.

    This step is common to users who are members of any type of organization.
    So `prescriber_org_data` will be the only modified value in the session.

    The SIRET is also the best way we have yet found to avoid duplicate organizations in the DB.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberSiretForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data["prescriber_org_data"] = form.org_data
        next_url = reverse("signup:prescriber_user")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


class PrescriberPoleEmploiUserSignupView(SignupView):
    """
    Create a user of type prescriber and make him join a pre-existing Pôle emploi organization.
    """

    form_class = forms.PrescriberPoleEmploiUserSignupForm
    template_name = "signup/prescriber_pole_emploi_user.html"

    @transaction.atomic
    @method_decorator(valid_prescriber_signup_session_required)
    @method_decorator(push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY))
    def dispatch(self, request, *args, **kwargs):

        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        kind = session_data.get("kind")
        pole_emploi_org_pk = session_data.get("pole_emploi_org_pk")

        # Check session data.
        if not pole_emploi_org_pk or kind != PrescriberOrganization.Kind.PE.value:
            raise PermissionDenied

        self.pole_emploi_org = get_object_or_404(
            PrescriberOrganization, pk=pole_emploi_org_pk, kind=PrescriberOrganization.Kind.PE.value
        )

        self.next = session_data.get("next")

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, **kwargs):
        kwargs = super().get_form_kwargs(**kwargs)
        kwargs["pole_emploi_org"] = self.pole_emploi_org
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pole_emploi_org"] = self.pole_emploi_org
        context["prev_url"] = get_prev_url_from_history(self.request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        return context

    def form_valid(self, form):
        # Drop the signup session.
        del self.request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        return super().form_valid(form)

    def get_success_url(self):
        # A ?next=URL param takes precedence.
        if self.next:
            return self.next
        return super().get_success_url()


class PrescriberUserSignupView(SignupView):
    """
    Create a new user of kind prescriber:

    - member of a new authorized organization ("prescripteur habilité")
    - or member of a new unauthorized organization ("orienteur")
    - or without any organization ("orienteur")

    The "authorized" character of a new organization is still to be validated by the support.
    """

    form_class = forms.PrescriberUserSignupForm
    template_name = "signup/prescriber_signup.html"

    @transaction.atomic
    @method_decorator(valid_prescriber_signup_session_required)
    @method_decorator(push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY))
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
        self.next = session_data.get("next")

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
                "prev_url": get_prev_url_from_history(self.request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
            }
        )
        return context

    def form_valid(self, form):
        # Drop the signup session.
        del self.request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        return super().form_valid(form)

    def get_success_url(self):
        # A ?next=URL param takes precedence.
        if self.next:
            return self.next
        return super().get_success_url()
