"""
Handle multiple user types sign up with django-allauth.
"""

import logging

from allauth.account.adapter import get_adapter
from allauth.account.views import PasswordResetFromKeyView, PasswordResetView, SignupView
from django.conf import settings
from django.contrib import auth, messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.db import Error, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.generic import FormView, TemplateView, View

from itou.common_apps.address.models import lat_lon_to_coords
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.adapter import UserAdapter
from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER, MATOMO_ACCOUNT_TYPE, UserKind
from itou.utils import constants as global_constants
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.nav_history import get_prev_url_from_history, push_url_in_history
from itou.utils.tokens import company_signup_token_generator
from itou.utils.urls import get_safe_url
from itou.www.signup import forms
from itou.www.signup.errors import JobSeekerSignupConflictModalResolver


logger = logging.getLogger(__name__)

ITOU_SESSION_FACILITATOR_SIGNUP_KEY = "facilitator_signup"


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
        args = urlencode({"email": form.data.get("email", "")})
        return HttpResponseRedirect(f"{self.get_success_url()}?{args}")


class ItouPasswordResetFromKeyView(PasswordResetFromKeyView):
    _user_is_new = None

    def user_is_new(self):
        if self._user_is_new is None:
            self._user_is_new = self.reset_user and not self.reset_user.last_login
        return self._user_is_new

    def get_context_data(self, **kwargs):
        ret = super().get_context_data(**kwargs)
        ret["user_is_new"] = self.user_is_new()
        ret["action_text"] = f"{'Enregistrer' if self.user_is_new() else 'Modifier'} le mot de passe"
        return ret

    def get_success_url(self):
        if self.user_is_new():
            # clear any pre-existing session and login the user
            self.request.session.clear()
            self.reset_user.emailaddress_set.filter(email=self.reset_user.email).update(verified=True)
            login(self.request, self.reset_user, backend="django.contrib.auth.backends.ModelBackend")
            return reverse("welcoming_tour:index")
        return super().get_success_url()


class ChooseUserKindSignupView(LoginNotRequiredMixin, FormView):
    template_name = "signup/choose_user_kind.html"
    form_class = forms.ChooseUserKindSignupForm

    def form_valid(self, form):
        urls = {
            UserKind.JOB_SEEKER: reverse("signup:job_seeker_start"),
            UserKind.PRESCRIBER: reverse("signup:prescriber_check_already_exists"),
            UserKind.EMPLOYER: reverse("signup:company_select"),
        }
        return HttpResponseRedirect(urls[form.cleaned_data["kind"]])


class JobSeekerStartSignupView(LoginNotRequiredMixin, TemplateView):
    template_name = "signup/job_seeker_start.html"


class JobSeekerSituationSignupView(LoginNotRequiredMixin, TemplateView):
    template_name = "signup/job_seeker_situation.html"


class JobSeekerCriteriaSignupView(LoginNotRequiredMixin, TemplateView):
    template_name = "signup/job_seeker_criteria.html"


@login_not_required
def job_seeker_signup_info(request, template_name="signup/job_seeker_signup.html"):
    form_class = forms.JobSeekerSignupWithOptionalNirForm if "skip" in request.POST else forms.JobSeekerSignupForm
    form = form_class(data=request.POST or None)

    if request.method == "POST":
        next_url = reverse("signup:job_seeker_credentials")

        form_is_valid = form.is_valid()

        # Regardless of whether there are form errors.
        # If there is a conflict with email or NIR, this class will present an error modal.
        JobSeekerSignupConflictModalResolver(
            form.cleaned_data, form.errors, form._nir_submitted, form._email_submitted
        ).evaluate(request)

        if form_is_valid:
            request.session[global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY] = form.cleaned_data

            # forward next page
            if REDIRECT_FIELD_NAME in form.data:
                next_url = f"{next_url}?{REDIRECT_FIELD_NAME}={form.data[REDIRECT_FIELD_NAME]}"

            return HttpResponseRedirect(next_url)
    elif request.method == "GET" and global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY in request.session:
        form = form_class(data=request.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY))

    context = {
        "form": form,
        "redirect_field_value": get_safe_url(request, REDIRECT_FIELD_NAME),
    }
    return render(request, template_name, context)


class JobSeekerCredentialsSignupView(LoginNotRequiredMixin, SignupView):
    form_class = forms.JobSeekerCredentialsSignupForm
    template_name = "signup/job_seeker_signup_credentials.html"

    def dispatch(self, request, *args, **kwargs):
        if global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY not in request.session:
            return HttpResponseRedirect(reverse("signup:job_seeker"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["show_france_connect"] = bool(settings.FRANCE_CONNECT_BASE_URL)
        context["show_peamu"] = bool(settings.PEAMU_AUTH_BASE_URL)
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["prior_cleaned_data"] = self.request.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        # Signup successful. Clear session
        self.request.session.pop(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)
        return response


# SIAEs signup.
# ------------------------------------------------------------------------------------------


@login_not_required
def company_select(request, template_name="signup/company_select.html"):
    """
    Entry point of the signup process for SIAEs which consists of 2 steps.

    The user is asked to select an SIAE based on a selection that match a given SIREN number.
    """

    companies_without_members = None
    companies_with_members = None

    next_url = get_safe_url(request, "next")

    siren_form = forms.CompanySearchBySirenForm(data=request.GET)
    company_select_form = None

    # The SIREN, when available, is always passed in the querystring.
    if request.method in ["GET", "POST"] and siren_form.is_valid():
        # Make sure to look only for active structures.
        companies_for_siren = (
            Company.objects.active().filter(siret__startswith=siren_form.cleaned_data["siren"]).distinct("pk")
        )
        # A user cannot join structures that already have members.
        # Show these structures in the template to make that clear.
        companies_with_members = (
            companies_for_siren.exclude(members=None)
            # the template directly displays the first membership's user "as the admin".
            # that's why we only select SIAEs that have at least an active admin user.
            # it should always be the case, but lets enforce it anyway.
            .filter(memberships__is_admin=True, memberships__user__is_active=True)
            # avoid the template issuing requests for every member and user.
            .prefetch_related("memberships__user")
        )
        companies_without_members = companies_for_siren.filter(members=None)
        company_select_form = forms.CompanySiaeSelectForm(data=request.POST or None, siaes=companies_without_members)

    if request.method == "POST" and company_select_form and company_select_form.is_valid():
        company_selected = company_select_form.cleaned_data["siaes"]
        company_selected.new_signup_activation_email_to_official_contact(request).send()
        message = (
            f"Nous venons d'envoyer un e-mail à l'adresse {company_selected.obfuscated_auth_email} "
            f"pour continuer votre inscription. Veuillez consulter votre boite "
            f"de réception."
        )
        messages.success(request, message)
        return HttpResponseRedirect(next_url or reverse("search:employers_home"))

    context = {
        "next_url": next_url,
        "companies_without_members": companies_without_members,
        "companies_with_members": companies_with_members,
        "company_select_form": company_select_form,
        "siren_form": siren_form,
    }
    return render(request, template_name, context)


class CompanyBaseView(View):
    def __init__(self):
        super().__init__()
        self.company = None
        self.token = None

    def setup(self, request, *args, **kwargs):
        self.token = kwargs["token"]
        super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, company_id, **kwargs):
        try:
            self.company = Company.objects.active().get(pk=company_id)
        except Company.DoesNotExist:
            self.company = None
        if self.company is None or not company_signup_token_generator.check_token(
            company=self.company, token=self.token
        ):
            messages.warning(
                request,
                "Ce lien d'inscription est invalide ou a expiré. Veuillez procéder à une nouvelle inscription.",
            )
            return HttpResponseRedirect(reverse("signup:company_select"))
        return super().dispatch(request, *args, **kwargs)


class CompanyUserView(LoginNotRequiredMixin, CompanyBaseView, TemplateView):
    """
    Display Inclusion Connect button.
    This page is also shown if an error is detected during
    OAuth callback.
    """

    template_name = "signup/employer.html"

    def get_context_data(self, **kwargs):
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": self.request.get_full_path(),
            "next_url": reverse("signup:company_join", args=(self.company.pk, self.token)),
        }
        pro_connect_url = (
            f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
        )
        return super().get_context_data(**kwargs) | {
            "pro_connect_url": pro_connect_url,
            "company": self.company,
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.EMPLOYER],
        }


class CompanyJoinView(CompanyBaseView):
    def get(self, request, *args, **kwargs):
        if not request.user.is_employer:
            logger.error("A non staff user tried to join a company")
            messages.error(
                request, "Vous ne pouvez pas rejoindre une structure avec ce compte car vous n'êtes pas employeur."
            )
            return HttpResponseRedirect(reverse("search:employers_home"))

        CompanyMembership.objects.create(
            user=request.user,
            company=self.company,
            # Only the first member becomes an admin.
            is_admin=self.company.active_members.count() == 0,
        )

        url = get_adapter(request).get_login_redirect_url(request)
        return HttpResponseRedirect(url)


# Prescribers signup.
# ------------------------------------------------------------------------------------------


def valid_prescriber_signup_session_required(function=None):
    def decorated(request, *args, **kwargs):
        session_data = request.session.get(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
        if not session_data:
            # Someone tries to use the direct link of a step inside the process
            # without going through the beginning.
            raise PermissionDenied
        return function(request, *args, **kwargs)

    return decorated


@login_not_required
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
    request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {
        "authorization_status": None,
        "email": None,
        "kind": None,
        "prescriber_org_data": None,
        "pole_emploi_org_pk": None,
        "safir_code": None,
        "url_history": [request.path],
        "next": get_safe_url(request, "next"),
    }

    prescriber_orgs_with_members_same_siret = None
    prescriber_orgs_with_members_same_siren = None

    form = forms.CheckAlreadyExistsForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
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
            return HttpResponseRedirect(
                reverse("signup:prescriber_choose_org", kwargs={"siret": form.cleaned_data["siret"]})
            )

    context = {
        "prescriber_orgs_with_members_same_siret": prescriber_orgs_with_members_same_siret,
        "prescriber_orgs_with_members_same_siren": prescriber_orgs_with_members_same_siren,
        "form": form,
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
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
            f"Votre demande d'ajout pour rejoindre « {prescriber_membership.organization.display_name} »"
            " a bien été envoyée."
        )
        messages.success(request, message)

        return redirect("dashboard:index")

    context = {
        "prescriber": prescriber_membership.user,
        "organization": prescriber_membership.organization,
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_choose_org(request, siret, template_name="signup/prescriber_choose_org.html"):
    """
    Ask the user to choose his organization in a pre-existing list of authorized organization.
    """
    form = forms.PrescriberChooseOrgKindForm(siret=siret, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
        session_data["prescriber_org_data"] = form.org_data
        request.session.modified = True

        prescriber_kind = form.cleaned_data["kind"]
        authorization_status = None

        if prescriber_kind == PrescriberOrganizationKind.FT.value:
            next_url = reverse("signup:prescriber_pole_emploi_safir_code")

        elif prescriber_kind == PrescriberOrganizationKind.OTHER.value:
            next_url = reverse("signup:prescriber_choose_kind")

        else:
            # A pre-existing kind of authorized organization was chosen.
            authorization_status = PrescriberAuthorizationStatus.NOT_SET.value
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
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_choose_kind(request, template_name="signup/prescriber_choose_kind.html"):
    """
    If the user hasn't found his organization in the pre-existing list, ask him to choose his kind.
    """

    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

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
            authorization_status = PrescriberAuthorizationStatus.NOT_REQUIRED.value
            kind = PrescriberOrganizationKind.OTHER.value

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
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_confirm_authorization(request, template_name="signup/prescriber_confirm_authorization.html"):
    """
    Ask the user to confirm the "authorized" character of his organization.

    That should help the support team with illegitimate or erroneous requests.
    """

    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberConfirmAuthorizationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        authorization_status = "NOT_SET" if form.cleaned_data["confirm_authorization"] else "NOT_REQUIRED"
        session_data.update(
            {
                "authorization_status": PrescriberAuthorizationStatus[authorization_status].value,
                "kind": PrescriberOrganizationKind.OTHER.value,
                "pole_emploi_org_pk": None,
                "safir_code": None,
            }
        )
        request.session.modified = True
        next_url = reverse("signup:prescriber_user")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_pole_emploi_safir_code(request, template_name="signup/prescriber_pole_emploi_safir_code.html"):
    """
    Find a pre-existing Pôle emploi organization from a given SAFIR code.
    """

    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    form = forms.PrescriberPoleEmploiSafirCodeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        session_data.update(
            {
                "authorization_status": None,
                "kind": PrescriberOrganizationKind.FT.value,
                "prescriber_org_data": None,
                "pole_emploi_org_pk": form.pole_emploi_org.pk,
                "safir_code": form.cleaned_data["safir_code"],
            }
        )
        request.session.modified = True
        next_url = reverse("signup:prescriber_check_pe_email")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_check_pe_email(request, template_name="signup/prescriber_check_pe_email.html"):
    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
    form = forms.PrescriberCheckPEemail(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        session_data["email"] = form.cleaned_data["email"]
        request.session.modified = True
        next_url = reverse("signup:prescriber_pole_emploi_user")
        return HttpResponseRedirect(next_url)

    kind = session_data.get("kind")
    pole_emploi_org_pk = session_data.get("pole_emploi_org_pk")

    # Check session data.
    if not pole_emploi_org_pk or kind != PrescriberOrganizationKind.FT.value:
        raise PermissionDenied

    pole_emploi_org = get_object_or_404(
        PrescriberOrganization, pk=pole_emploi_org_pk, kind=PrescriberOrganizationKind.FT.value
    )
    context = {
        "pole_emploi_org": pole_emploi_org,
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_pole_emploi_user(request, template_name="signup/prescriber_pole_emploi_user.html"):
    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
    kind = session_data.get("kind")
    pole_emploi_org_pk = session_data.get("pole_emploi_org_pk")

    # Check session data.
    if not pole_emploi_org_pk or kind != PrescriberOrganizationKind.FT.value:
        raise PermissionDenied

    pole_emploi_org = get_object_or_404(
        PrescriberOrganization, pk=pole_emploi_org_pk, kind=PrescriberOrganizationKind.FT.value
    )
    params = {
        "user_email": session_data["email"],
        "user_kind": KIND_PRESCRIBER,
        "previous_url": request.get_full_path(),
        "next_url": reverse("signup:prescriber_join_org"),
    }
    pro_connect_url = (
        f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
    )

    context = {
        "pro_connect_url": pro_connect_url,
        "pole_emploi_org": pole_emploi_org,
        "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.PRESCRIBER],
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@login_not_required
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_user(request, template_name="signup/prescriber_user.html"):
    """
    Display Inclusion Connect button.
    This page is also shown if an error is detected during
    OAuth callback.
    """
    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]
    authorization_status = session_data.get("authorization_status")
    prescriber_org_data = session_data.get("prescriber_org_data")
    kind = session_data.get("kind")

    join_as_orienteur_without_org = kind is None and authorization_status is None and prescriber_org_data is None

    join_as_orienteur_with_org = (
        authorization_status == PrescriberAuthorizationStatus.NOT_REQUIRED.value
        and kind == PrescriberOrganizationKind.OTHER.value
        and prescriber_org_data is not None
    )

    join_authorized_org = (
        authorization_status == PrescriberAuthorizationStatus.NOT_SET.value
        and kind not in [None, PrescriberOrganizationKind.FT.value]
        and prescriber_org_data is not None
    )

    # Check session data. There can be only one kind.
    if sum([join_as_orienteur_without_org, join_as_orienteur_with_org, join_authorized_org]) != 1:
        raise PermissionDenied

    if kind not in PrescriberOrganizationKind.values:
        kind = None

    try:
        authorization_status = PrescriberAuthorizationStatus[authorization_status]
    except KeyError:
        authorization_status = None

    # Get kind label
    kind_label = dict(PrescriberOrganizationKind.choices).get(kind)

    params = {
        "user_kind": KIND_PRESCRIBER,
        "previous_url": request.get_full_path(),
    }
    if join_as_orienteur_with_org or join_authorized_org:
        # Redirect to the join organization view after login or signup.
        params["next_url"] = reverse("signup:prescriber_join_org")

    pro_connect_url = (
        f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
    )

    context = {
        "pro_connect_url": pro_connect_url,
        "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.PRESCRIBER],
        "join_as_orienteur_without_org": join_as_orienteur_without_org,
        "join_authorized_org": join_authorized_org,
        "kind_label": kind_label,
        "kind_is_other": kind == PrescriberOrganizationKind.OTHER.value,
        "prescriber_org_data": prescriber_org_data,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_join_org(request):
    """
    User is redirected here after a successful oauth signup.
    This is the last step of the signup path.
    """
    if not request.user.is_prescriber:
        messages.error(
            request, "Vous ne pouvez pas rejoindre une organisation avec ce compte car vous n'êtes pas prescripteur."
        )
        return HttpResponseRedirect(reverse("search:employers_home"))

    # Get useful information from session.
    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    try:
        with transaction.atomic():
            if session_data["kind"] == "FT":
                # Organization creation is not allowed for FT.
                pole_emploi_org_pk = session_data.get("pole_emploi_org_pk")
                # We should not have errors here since we have a FT organization pk from the database.
                prescriber_org = PrescriberOrganization.objects.get(
                    pk=pole_emploi_org_pk, kind=PrescriberOrganizationKind.FT.value
                )
            else:
                org_attributes = {
                    "siret": session_data["prescriber_org_data"]["siret"],
                    "name": session_data["prescriber_org_data"]["name"],
                    "address_line_1": session_data["prescriber_org_data"]["address_line_1"] or "",
                    "address_line_2": session_data["prescriber_org_data"]["address_line_2"] or "",
                    "post_code": session_data["prescriber_org_data"]["post_code"],
                    "city": session_data["prescriber_org_data"]["city"],
                    "department": session_data["prescriber_org_data"]["department"],
                    "coords": lat_lon_to_coords(
                        session_data["prescriber_org_data"]["latitude"],
                        session_data["prescriber_org_data"]["longitude"],
                    ),
                    "geocoding_score": session_data["prescriber_org_data"]["geocoding_score"],
                    "kind": session_data["kind"],
                    "authorization_status": session_data["authorization_status"],
                    "created_by": request.user,
                }
                prescriber_org = PrescriberOrganization.objects.create_organization(attributes=org_attributes)

            prescriber_org.add_or_activate_membership(user=request.user)

    except Error:
        messages.error(request, "L'organisation n'a pas pu être créée")
        # Logout user from any SSO and redirect to homepage.
        # As we cannot logout with GET nor redirect as POST to the logout page,
        # we need to do it manually.
        redirect_url = UserAdapter().get_logout_redirect_url(request)
        auth.logout(request)
        return HttpResponseRedirect(redirect_url)

    # redirect to post login page.
    next_url = get_adapter(request).get_login_redirect_url(request)
    # delete session data
    request.session.pop(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
    request.session.modified = True
    return HttpResponseRedirect(next_url)


# Facilitator signup.
# ------------------------------------------------------------------------------------------


class FacilitatorBaseMixin:
    def dispatch(self, request, *args, **kwargs):
        if ITOU_SESSION_FACILITATOR_SIGNUP_KEY not in request.session:
            return HttpResponseRedirect(reverse("signup:facilitator_search"))
        self._get_session_siae()
        return super().dispatch(request, *args, **kwargs)

    def _get_session_siae(self):
        org_data = self.request.session[ITOU_SESSION_FACILITATOR_SIGNUP_KEY]
        self.company_to_create = Company(
            kind=CompanyKind.OPCS,
            source=Company.SOURCE_USER_CREATED,
            siret=org_data["siret"],
            name=org_data["name"],
            address_line_1=org_data["address_line_1"] or "",
            address_line_2=org_data["address_line_2"] or "",
            post_code=org_data["post_code"],
            city=org_data["city"],
            department=org_data["department"],
            email="",  # not public
            auth_email="",  # filled in the form
            phone="",
            geocoding_score=org_data["geocoding_score"],
            coords=lat_lon_to_coords(org_data.get("latitude"), org_data.get("longitude")),
            created_by=None,
            is_searchable=False,  # Wait for admin to check the company
        )


@login_not_required
def facilitator_search(request, template_name="signup/facilitator_search.html"):
    form = forms.FacilitatorSearchForm(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session[ITOU_SESSION_FACILITATOR_SIGNUP_KEY] = form.org_data
        return HttpResponseRedirect(reverse("signup:facilitator_user"))

    context = {
        "form": form,
        "prev_url": reverse("signup:company_select"),
    }
    return render(request, template_name, context)


class FacilitatorUserView(LoginNotRequiredMixin, FacilitatorBaseMixin, TemplateView):
    """
    Display Inclusion Connect button.
    This page is also shown if an error is detected during
    OAuth callback.
    """

    template_name = "signup/employer.html"

    def get_context_data(self, **kwargs):
        params = {
            "user_kind": KIND_EMPLOYER,
            "previous_url": self.request.get_full_path(),
            "next_url": reverse("signup:facilitator_join"),
        }
        pro_connect_url = (
            f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
        )
        return super().get_context_data(**kwargs) | {
            "pro_connect_url": pro_connect_url,
            "company": self.company_to_create,
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[UserKind.EMPLOYER],
        }


class FacilitatorJoinView(LoginNotRequiredMixin, FacilitatorBaseMixin, View):
    def get(self, request, *args, **kwargs):
        self.company_to_create.auth_email = request.user.email
        self.company_to_create.created_by = request.user
        self.company_to_create.save()

        CompanyMembership.objects.create(
            user=request.user,
            company=self.company_to_create,
            is_admin=True,  # by construction, this user is the first of the SIAE.
        )

        # redirect to post login page.
        next_url = get_adapter(request).get_login_redirect_url(request)
        # delete session data
        request.session.pop(ITOU_SESSION_FACILITATOR_SIGNUP_KEY)
        request.session.modified = True
        return HttpResponseRedirect(next_url)
