"""
Handle multiple user types sign up with django-allauth.
"""

import logging

from allauth.account.adapter import get_adapter
from allauth.account.views import PasswordResetFromKeyView, PasswordResetView, SignupView
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, login
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.db import Error, transaction
from django.db.models import Exists, OuterRef, Prefetch
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.generic import FormView, TemplateView, View

from itou.common_apps.address.models import lat_lon_to_coords
from itou.companies.enums import CompanyKind, CompanySource
from itou.companies.models import Company, CompanyMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER, KIND_PROFESSIONAL, UserKind
from itou.utils import constants as global_constants
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.legal_terms import bypass_terms_acceptance
from itou.utils.nav_history import get_prev_url_from_history, push_url_in_history
from itou.utils.tokens import company_signup_token_generator
from itou.utils.urls import get_safe_url, get_zendesk_form_url
from itou.utils.views import with_triggers_context
from itou.www.signup import forms
from itou.www.signup.errors import JobSeekerSignupConflictModalResolver


logger = logging.getLogger(__name__)

ITOU_SESSION_FACILITATOR_SIGNUP_KEY = "facilitator_signup"


def get_pro_post_join_redirect_url(request, org):
    # redirect to post login page.
    next_url = get_adapter(request).get_login_redirect_url(request)
    # Switch to new membership
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = org.organization_switch_key
    request.session.modified = True
    return next_url


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
            login(self.request, self.reset_user)
            return reverse("welcoming_tour:index")
        return super().get_success_url()


class ChooseUserKindSignupView(LoginNotRequiredMixin, FormView):
    template_name = "signup/choose_user_kind.html"
    form_class = forms.ChooseUserKindSignupForm

    def form_valid(self, form):
        urls = {
            UserKind.JOB_SEEKER: reverse("signup:job_seeker_start"),
            KIND_PROFESSIONAL: reverse("signup:professional_user"),
        }
        return HttpResponseRedirect(urls[form.cleaned_data["kind"]])


# Job Seeker signup.
# ------------------------------------------------------------------------------------------


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


@method_decorator(with_triggers_context, name="dispatch")
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


# Professional generic signup.
# ------------------------------------------------------------------------------------------


@login_not_required
def professional_user(request, template_name="signup/professional_user.html"):
    """
    Display ProConnect button.
    This page is also shown if an error is detected during
    OAuth callback.
    """

    params = {
        "previous_url": request.get_full_path(),
        "next_url": reverse("signup:choose_pro_membership_kind"),
    }

    pro_connect_url = (
        f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
    )

    context = {"pro_connect_url": pro_connect_url}
    return render(request, template_name, context)


class ChooseMembershipKindView(FormView):
    template_name = "signup/choose_membership_kind.html"
    form_class = forms.ChooseMembershipKindForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["is_ft_user"] = self.request.user.email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX)
        return kwargs

    def form_valid(self, form):
        urls = {
            # Only available for FT user in ChooseMembershipKindForm
            PrescriberOrganizationKind.FT: reverse("signup:prescriber_search_ft_org"),
            KIND_PRESCRIBER: reverse("signup:prescriber_check_already_exists"),
            KIND_EMPLOYER: reverse("signup:company_select"),
        }
        return HttpResponseRedirect(urls[form.cleaned_data["kind"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_ft_user"] = self.get_form_kwargs()["is_ft_user"]
        return context


# SIAEs signup.
# ------------------------------------------------------------------------------------------


def company_select(request, template_name="signup/company_select.html"):
    """
    Entry point of the signup process for companies.

    Registering user is asked to select a company from those matching a given SIREN number.
    We distinguish between companies with and without active members because:
    - if a company has no active member, one can register autonomously by selecting (in the form) the company to which
    an email will be sent (cf. Company.auth_email).
    - if a company has at least one active member, one can register only by reaching to another member of that company.
    In the latter case, the template displays the first (admin if any) member of the company as its contact person.
    """

    companies_without_active_members = None
    companies_with_active_members = None

    next_url = get_safe_url(request, "next")
    data = request.GET.copy()
    if next_url:
        data.pop("next")

    # Form with required field is validated on GET, so instanciate the form with None when there's no querystring
    siren_form = forms.CompanySearchBySirenForm(data=data or None)
    company_select_form = None

    # The SIREN, when available, is always passed as a URL parameter.
    if request.method in ["GET", "POST"] and siren_form.is_valid():
        # We make admin members (if any) from the company appear at the beginning of the final QuerySet so the contact
        # person is more likely to be an admin when displaying the results.
        memberships_qs = CompanyMembership.objects.select_related("user").order_by("-is_admin", "joined_at")
        companies_for_siren = (
            # Make sure to look only for active companies.
            Company.objects.active()
            .filter(siret__startswith=siren_form.cleaned_data["siren"])
            .distinct("pk")
            .annotate(has_active_members=Exists(CompanyMembership.objects.filter(company=OuterRef("pk"))))
            # Prevents the template from reissuing a request for each member/user.
            .prefetch_related(Prefetch("memberships", queryset=memberships_qs))
        )
        companies_without_active_members = companies_for_siren.filter(has_active_members=False)
        companies_with_active_members = companies_for_siren.filter(has_active_members=True)
        company_select_form = forms.CompanySiaeSelectForm(
            data=request.POST or None, siaes=companies_without_active_members
        )

    if request.method == "POST" and company_select_form and company_select_form.is_valid():
        company_selected = company_select_form.cleaned_data["siaes"]
        obfuscated_auth_email = company_selected.obfuscated_auth_email
        if not obfuscated_auth_email:
            messages.error(
                request,
                mark_safe(
                    "L’adresse e-mail de contact du gestionnaire de cette structure n’est pas renseignée. Merci de "
                    f'<a href="{get_zendesk_form_url(request)}" target="_blank" rel="noopener" '
                    'class="has-external-link">contacter notre support technique</a> afin de poursuivre votre'
                    "inscription."
                ),
            )
        else:
            company_selected.new_signup_activation_email_to_official_contact().send()
            message = (
                f"Nous venons d'envoyer un e-mail à l'adresse {company_selected.obfuscated_auth_email} "
                f"pour poursuivre votre inscription. Veuillez consulter votre boite "
                f"de réception."
            )
            messages.success(request, message)
            return HttpResponseRedirect(next_url or reverse("dashboard:index"))

    context = {
        "next_url": next_url,
        "companies_without_active_members": companies_without_active_members,
        "companies_with_active_members": companies_with_active_members,
        "company_select_form": company_select_form,
        "siren_form": siren_form,
        "prev_url": reverse("signup:choose_pro_membership_kind"),
        "reset_url": reverse("dashboard:index"),
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
    Display ProConnect button.
    This page is also shown if an error is detected during
    OAuth callback.
    """

    template_name = "signup/employer.html"

    def dispatch(self, request, *args, company_id, token, **kwargs):
        parent_dispatch = super().dispatch(request, *args, company_id=company_id, **kwargs)
        if isinstance(parent_dispatch, HttpResponseRedirect):
            return parent_dispatch
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse("signup:company_join", args=(company_id, token)))
        return parent_dispatch

    def get_context_data(self, **kwargs):
        params = {
            "previous_url": self.request.get_full_path(),
            "next_url": reverse("signup:company_join", args=(self.company.pk, self.token)),
        }
        pro_connect_url = (
            f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
        )
        return super().get_context_data(**kwargs) | {
            "pro_connect_url": pro_connect_url,
            "company": self.company,
        }


@method_decorator(bypass_terms_acceptance, name="dispatch")
class CompanyJoinView(CompanyBaseView):
    def get(self, request, *args, **kwargs):
        if not request.user.is_professional:
            logger.error("A non professional user tried to join a company")
            messages.error(
                request, "Vous ne pouvez pas rejoindre une structure avec ce compte car vous n'êtes pas professionnel."
            )
            return HttpResponseRedirect(reverse("search:employers_results"))

        membership = CompanyMembership.objects.create(
            user=request.user,
            company=self.company,
            # Only the first member becomes an admin.
            is_admin=self.company.active_members.count() == 0,
        )

        next_url = get_pro_post_join_redirect_url(request, membership.company)
        return HttpResponseRedirect(next_url)


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


def prescriber_check_already_exists(request, template_name="signup/prescriber_check_already_exists.html"):
    """

    Entry point of the signup process for prescribers/orienteurs not from France Travail.

    The signup process consists of several steps during which the user answers
    a series of questions to determine the `kind` of his organization if any.

    Answers are kept in session.

    At the end of the process the user will:
    - be added to the members of a new authorized organization ("prescripteur habilité")
    - be added to the members of a new unauthorized organization ("orienteur")
    - request an invitation to an existing organization (authorized or not)

    This first Step makes it possible to avoid duplicates of prescriber's organizations.
    """

    # Start a fresh session that will be used during the signup process.
    # Since we can go back-and-forth, or someone always has the option
    # of using a direct link, its state must be kept clean in each step.
    request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY] = {
        "authorization_status": None,
        "email": None,
        "kind": None,
        "prescriber_org_data": None,
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
        "prev_url": reverse("signup:choose_pro_membership_kind"),
        "reset_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
@require_POST
def prescriber_request_invitation(request, membership_id):
    prescriber_membership = get_object_or_404(
        PrescriberMembership.objects.select_related("organization", "user"), pk=membership_id
    )
    # Send e-mail to the member of the organization
    prescriber_membership.request_for_invitation(request.user).send()

    message = (
        f"Votre demande d'ajout pour rejoindre « {prescriber_membership.organization.display_name} »"
        " a bien été envoyée."
    )
    messages.success(request, message)
    request.session.pop(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
    request.session.modified = True
    return redirect("dashboard:index")


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

        if prescriber_kind == PrescriberOrganizationKind.OTHER.value:
            next_url = reverse("signup:prescriber_choose_kind")

        else:
            # A pre-existing kind of authorized organization was chosen.
            authorization_status = PrescriberAuthorizationStatus.NOT_SET.value
            next_url = reverse("signup:prescriber_join_org")

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": prescriber_kind,
            }
        )
        request.session.modified = True
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
        "reset_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


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
            else "signup:prescriber_join_org"
        )

        if prescriber_kind == form.KIND_UNAUTHORIZED_ORG:
            authorization_status = PrescriberAuthorizationStatus.NOT_REQUIRED.value
            kind = PrescriberOrganizationKind.OTHER.value

        session_data.update(
            {
                "authorization_status": authorization_status,
                "kind": kind,
            }
        )
        request.session.modified = True
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
        "reset_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


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
            }
        )
        request.session.modified = True
        next_url = reverse("signup:prescriber_join_org")
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": get_prev_url_from_history(request, global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY),
        "reset_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@bypass_terms_acceptance
@valid_prescriber_signup_session_required
@push_url_in_history(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
def prescriber_join_org(request):
    """
    This is the last step of the signup path.
    """
    if not request.user.is_professional:
        messages.error(
            request, "Vous ne pouvez pas rejoindre une organisation avec ce compte car vous n'êtes pas professionnel."
        )
        return HttpResponseRedirect(reverse("search:employers_results"))

    # Get useful information from session.
    session_data = request.session[global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY]

    authorization_status = session_data.get("authorization_status")
    kind = session_data.get("kind")

    join_non_authorized_org = (
        authorization_status == PrescriberAuthorizationStatus.NOT_REQUIRED.value
        and kind == PrescriberOrganizationKind.OTHER.value
    )

    join_authorized_org = kind in PrescriberOrganizationKind.FT.value or (
        authorization_status == PrescriberAuthorizationStatus.NOT_SET.value and kind is not None
    )

    # Check session data. There can be only one kind.
    if sum([join_non_authorized_org, join_authorized_org]) != 1:
        raise PermissionDenied

    try:
        with transaction.atomic():
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
        return HttpResponseRedirect(reverse("signup:prescriber_check_already_exists"))

    request.session.pop(global_constants.ITOU_SESSION_PRESCRIBER_SIGNUP_KEY)
    request.session.modified = True
    next_url = get_pro_post_join_redirect_url(request, prescriber_org)
    return HttpResponseRedirect(next_url)


# FT prescriber signup.
# ------------------------------------------------------------------------------------------


def prescriber_search_ft_org(request, template_name="signup/prescriber_search_ft_org.html"):
    """
    Find a pre-existing France Travail organization from a given SAFIR code.
    """

    if not request.user.email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX):
        raise PermissionDenied()

    form = forms.PrescriberPoleEmploiSafirCodeForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        next_url = reverse("signup:prescriber_join_ft_org", kwargs={"uuid": form.pole_emploi_org.uid})
        return HttpResponseRedirect(next_url)

    context = {
        "form": form,
        "prev_url": reverse("signup:choose_pro_membership_kind"),
        "reset_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


def prescriber_join_ft_org(request, uuid, template_name="signup/prescriber_join_ft_org.html"):
    """
    Join the given organization
    """
    if not request.user.email.endswith(global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX):
        raise PermissionDenied()

    ft_org = get_object_or_404(PrescriberOrganization, uid=uuid, kind=PrescriberOrganizationKind.FT.value)
    already_member = ft_org.has_member(request.user)

    if request.method == "POST" and not already_member:
        ft_org.add_or_activate_membership(user=request.user)
        next_url = get_pro_post_join_redirect_url(request, ft_org)
        return HttpResponseRedirect(next_url)

    return render(
        request,
        template_name,
        {
            "ft_org": ft_org,
            "already_member": already_member,
            "prev_url": reverse("signup:prescriber_search_ft_org"),
            "reset_url": reverse("dashboard:index"),
        },
    )


# Facilitator signup.
# ------------------------------------------------------------------------------------------


def facilitator_search(request, template_name="signup/facilitator_search.html"):
    form = forms.FacilitatorSearchForm(data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session[ITOU_SESSION_FACILITATOR_SIGNUP_KEY] = form.org_data
        return HttpResponseRedirect(reverse("signup:facilitator_join"))

    context = {
        "form": form,
        "prev_url": reverse("signup:company_select"),
    }
    return render(request, template_name, context)


def facilitator_join(request, template_name="signup/facilitator_join.html"):
    if ITOU_SESSION_FACILITATOR_SIGNUP_KEY not in request.session:
        return HttpResponseRedirect(reverse("signup:facilitator_search"))

    org_data = request.session[ITOU_SESSION_FACILITATOR_SIGNUP_KEY]
    company_to_create = Company.objects.create(
        kind=CompanyKind.OPCS,
        source=CompanySource.USER_CREATED,
        siret=org_data["siret"],
        name=org_data["name"],
        address_line_1=org_data["address_line_1"] or "",
        address_line_2=org_data["address_line_2"] or "",
        post_code=org_data["post_code"],
        city=org_data["city"],
        department=org_data["department"],
        email="",  # not public
        auth_email=request.user.email,
        phone="",
        geocoding_score=org_data["geocoding_score"],
        coords=lat_lon_to_coords(org_data.get("latitude"), org_data.get("longitude")),
        created_by=request.user,
        is_searchable=False,  # Wait for admin to check the company
    )

    CompanyMembership.objects.create(
        user=request.user,
        company=company_to_create,
        is_admin=True,  # by construction, this user is the first of the SIAE.
    )

    # delete session data
    request.session.pop(ITOU_SESSION_FACILITATOR_SIGNUP_KEY)
    request.session.modified = True
    return render(request, template_name)
