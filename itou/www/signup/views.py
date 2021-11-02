"""
Handle multiple user types sign up with django-allauth.
"""
import logging

from allauth.account.views import PasswordResetView, SignupView
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.views.decorators.http import require_GET

from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.nav_history import get_prev_url_from_history, push_url_in_history
from itou.utils.urls import get_safe_url
from itou.www.signup import forms


logger = logging.getLogger(__name__)


class ItouPasswordResetView(PasswordResetView):
    def form_valid(self, form):
        form.save(self.request)
        # Pass the email in the querystring so that it can displayed in the template.
        args = urlencode({"email": form.data["email"]})
        return HttpResponseRedirect(f"{self.get_success_url()}?{args}")

    def form_invalid(self, form):
        """
        Avoid user enumeration: django-allauth displays an error message to the user
        when an email does not exist. We deliberately hide it by redirecting to the
        success page in all cases.
        """
        # Pass the email in the querystring so that it can displayed in the template.
        args = urlencode({"email": form.data["email"]})
        return HttpResponseRedirect(f"{self.get_success_url()}?{args}")


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show_france_connect"] = settings.FRANCE_CONNECT_ENABLED
        context["show_peamu"] = True
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["nir"] = self.request.session.get(settings.ITOU_SESSION_NIR_KEY)
        return kwargs

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """Enforce atomicity."""
        return super().post(request, *args, **kwargs)


def job_seeker_situation(
    request, template_name="signup/job_seeker_situation.html", redirect_field_name=REDIRECT_FIELD_NAME
):
    """
    Second step of the signup process for jobseeker.

    The user is asked to choose at least one eligibility criterion to continue the signup process.
    """

    form = forms.JobSeekerSituationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        next_url = reverse("signup:job_seeker_situation_not_eligible")

        # If at least one of the eligibility choices is selected, go to the signup form.
        if any(choice in forms.JobSeekerSituationForm.ELIGIBLE_SITUATION for choice in form.cleaned_data["situation"]):
            next_url = reverse("signup:job_seeker_nir")

        # forward next page
        if redirect_field_name in form.data:
            next_url = f"{next_url}?{redirect_field_name}={form.data[redirect_field_name]}"

        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "redirect_field_name": redirect_field_name,
        "redirect_field_value": get_safe_url(request, redirect_field_name),
    }
    return render(request, template_name, context)


def job_seeker_nir(request, template_name="signup/job_seeker_nir.html", redirect_field_name=REDIRECT_FIELD_NAME):
    form = forms.JobSeekerNirForm(data=request.POST or None)

    if request.method == "POST":
        next_url = reverse("signup:job_seeker")
        if form.is_valid():
            request.session[settings.ITOU_SESSION_NIR_KEY] = form.cleaned_data["nir"]

            # forward next page
            if redirect_field_name in form.data:
                next_url = f"{next_url}?{redirect_field_name}={form.data[redirect_field_name]}"

            return HttpResponseRedirect(next_url)

        if form.data.get("skip"):
            return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "redirect_field_name": redirect_field_name,
        "redirect_field_value": get_safe_url(request, redirect_field_name),
    }
    return render(request, template_name, context)


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
        message = (
            f"Nous venons d'envoyer un e-mail à l'adresse {siae_selected.obfuscated_auth_email} "
            f"pour continuer votre inscription. Veuillez consulter votre boite "
            f"de réception."
        )
        messages.success(request, message)
        return HttpResponseRedirect(next_url or "/")

    context = {
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
            request, "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription."
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


def prescriber_check_already_exists(request, template_name="signup/prescriber_check_already_exists.html"):
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

    Step 1: makes it possible to avoid duplicates of prescriber's organizations.
    As 80% of prescribers on Itou are Pôle emploi members, a link is dedicated for users who work for PE.
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

    prescriber_orgs_with_members_same_siret = None
    prescriber_orgs_with_members_same_siren = None

    form = forms.PrescriberCheckAlreadyExistsForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():

        # Puts the data from API entreprise and geocoding in session for the last creation step
        session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        session_data["prescriber_org_data"] = form.org_data
        request.session.modified = True

        # Get organizations with members with precisely the same SIRET
        prescriber_orgs_with_members_same_siret = PrescriberOrganization.objects.prefetch_active_memberships().filter(
            siret=form.cleaned_data["siret"]
        )

        # Get organizations with members with same SIREN but not the same SIRET
        prescriber_orgs_with_members_same_siren = (
            PrescriberOrganization.objects.prefetch_active_memberships()
            .filter(siret__startswith=form.cleaned_data["siret"][:9], department=form.cleaned_data["department"])
            .exclude(members=None)
            .exclude(pk__in=[p.pk for p in prescriber_orgs_with_members_same_siret])
        )

        # Redirect to creation steps if no organization with member is found,
        # else, displays the same form with the list of organizations with first member
        # to indicate which person to request an invitation from
        if not prescriber_orgs_with_members_same_siret and not prescriber_orgs_with_members_same_siren:
            return HttpResponseRedirect(reverse("signup:prescriber_choose_org"))

    context = {
        "prescriber_orgs_with_members_same_siret": prescriber_orgs_with_members_same_siret,
        "prescriber_orgs_with_members_same_siren": prescriber_orgs_with_members_same_siren,
        "form": form,
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_request_invitation(request, membership_id, template_name="signup/prescriber_request_invitation.html"):

    prescriber_membership = get_object_or_404(
        PrescriberMembership.objects.select_related("organization", "user"), pk=membership_id
    )

    form = forms.PrescriberRequestInvitationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        requestor = {
            "first_name": form.cleaned_data["first_name"],
            "last_name": form.cleaned_data["last_name"],
            "email": form.cleaned_data["email"],
        }
        # Send e-mail to the member of the organization
        prescriber_membership.request_for_invitation(requestor).send()

        message = (
            f"Votre demande d'invitation à rejoindre « {prescriber_membership.organization.display_name} »"
            " a été envoyée par courriel."
        )
        messages.success(request, message)

        return redirect("home:hp")

    context = {
        "prescriber": prescriber_membership.user,
        "organization": prescriber_membership.organization,
        "form": form,
        "prev_url": get_prev_url_from_history(request, settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_choose_org(request, template_name="signup/prescriber_choose_org.html"):
    """
    Ask the user to choose his organization in a pre-existing list of authorized organization.
    """

    session_data = request.session[settings.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
    prescriber_org_data = session_data.get("prescriber_org_data")

    form = forms.PrescriberChooseOrgKindForm(siret=prescriber_org_data.get("siret"), data=request.POST or None)

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
            next_url = reverse("signup:prescriber_user")

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": prescriber_kind,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        request.session.modified = True
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

        next_url = reverse(
            "signup:prescriber_confirm_authorization"
            if prescriber_kind == form.KIND_AUTHORIZED_ORG
            else "signup:prescriber_user"
        )

        if prescriber_kind == form.KIND_UNAUTHORIZED_ORG:
            authorization_status = PrescriberOrganization.AuthorizationStatus.NOT_REQUIRED.value
            kind = PrescriberOrganization.Kind.OTHER.value

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": kind,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        request.session.modified = True
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
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        request.session.modified = True
        next_url = reverse("signup:prescriber_user")
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
        request.session.modified = True
        next_url = reverse("signup:prescriber_pole_emploi_user")
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

        if kind not in PrescriberOrganization.Kind.values:
            kind = None

        try:
            authorization_status = PrescriberOrganization.AuthorizationStatus[authorization_status]
        except KeyError:
            authorization_status = None

        self.authorization_status = authorization_status
        self.kind = kind
        # Get kind label
        self.kind_label = dict(PrescriberOrganization.Kind.choices).get(kind)
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
                "kind_label": self.kind_label,
                "kind_is_other": self.kind == PrescriberOrganization.Kind.OTHER.value,
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
