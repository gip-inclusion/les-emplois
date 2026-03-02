from allauth.account.adapter import get_adapter
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import PermissionDenied
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.forms import modelformset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.urls import reverse_lazy
from django.utils import formats, safestring
from django.views.generic import TemplateView

from itou.invitations.models import (
    EmployerInvitation,
    InvitationAbstract,
    LaborInspectorInvitation,
    PrescriberWithOrgInvitation,
)
from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.users.enums import KIND_EMPLOYER, KIND_LABOR_INSPECTOR, KIND_PRESCRIBER, MATOMO_ACCOUNT_TYPE
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.templatetags.str_filters import pluralizefr
from itou.www.invitations_views.forms import (
    BaseEmployerInvitationFormSet,
    BaseLaborInspectorInvitationFormSet,
    BasePrescriberWithOrgInvitationFormSet,
    EmployerInvitationForm,
    LaborInspectorInvitationForm,
    NewUserInvitationForm,
    PrescriberWithOrgInvitationForm,
)
from itou.www.invitations_views.helpers import (
    handle_employer_invitation,
    handle_labor_inspector_invitation,
    handle_prescriber_intivation,
)
from itou.www.signup import forms as signup_forms


MAX_PENDING_INVITATION = 50


def handle_invited_user_registration_with_django(request, invitation, invitation_type):
    # This view is now only used for labor inspectors
    form = NewUserInvitationForm(data=request.POST or None, invitation=invitation)
    if form.is_valid():
        user = form.save(request)
        get_adapter().login(request, user)
        return redirect(invitation.acceptance_url_for_existing_user)
    context = {"form": form, "invitation": invitation}
    return render(request, "invitations_views/new_user.html", context=context)


def handle_invited_user_registration_with_pro_connect(request, invitation, invitation_type):
    query = {
        "user_kind": invitation_type,
        "user_email": invitation.email,
        "channel": ProConnectChannel.INVITATION.value,
        "previous_url": request.get_full_path(),
        "next_url": invitation.acceptance_url_for_existing_user,
    }
    pro_connect_url = reverse("pro_connect:authorize", query=query) if settings.PRO_CONNECT_BASE_URL else None
    context = {
        "pro_connect_url": pro_connect_url,
        "invitation": invitation,
        "matomo_account_type": MATOMO_ACCOUNT_TYPE[invitation_type],
    }
    return render(request, "invitations_views/new_pro_connect_user.html", context=context)


@login_not_required
def new_user(request, invitation_type, invitation_id):
    if invitation_type not in [KIND_LABOR_INSPECTOR, KIND_PRESCRIBER, KIND_EMPLOYER]:
        messages.error(request, "Ce lien n'est plus valide.")
        return redirect(reverse("search:employers_home"))
    invitation_class = InvitationAbstract.get_model_from_string(invitation_type)
    invitation = get_object_or_404(invitation_class, pk=invitation_id)

    if request.user.is_authenticated:
        if not request.user.email.lower() == invitation.email.lower():
            message = (
                "Un utilisateur est déjà connecté.<br>"
                "Merci de déconnecter ce compte en cliquant sur le bouton ci-dessous. "
                "La page d'accueil se chargera automatiquement, n'en tenez pas compte.<br>"
                "Retournez dans votre boite mail et cliquez de nouveau sur le lien "
                "reçu pour accepter l'invitation."
            )
            message = safestring.mark_safe(message)
            messages.error(request, message)
            return redirect("account_logout")

    if not invitation.can_be_accepted:
        messages.error(request, "Ce lien n'est plus valide.")
        return render(request, "invitations_views/invitation_errors.html", context={"invitation": invitation})

    if invitation_type == KIND_EMPLOYER and not invitation.company.is_active:
        messages.error(request, "La structure que vous souhaitez rejoindre n'est plus active.")
        return render(request, "invitations_views/invitation_errors.html", context={"invitation": invitation})

    if User.objects.filter(email__iexact=invitation.email).exists():
        if request.user.is_authenticated:
            # We know that request.user.email & invitation.email match
            # so let's skip the login dance
            return redirect(invitation.acceptance_url_for_existing_user)

        # The user exists but he should log in first.
        login_url = reverse(
            f"login:{invitation.USER_KIND}", query={"next": invitation.acceptance_url_for_existing_user}
        )
        return redirect(login_url)

    # A new user should be created before joining
    handle_registration = {
        KIND_PRESCRIBER: handle_invited_user_registration_with_pro_connect,
        KIND_EMPLOYER: handle_invited_user_registration_with_pro_connect,
        KIND_LABOR_INSPECTOR: handle_invited_user_registration_with_django,
    }[invitation_type]
    return handle_registration(request, invitation, invitation_type)


def _toast_invitation_sent(invitations):
    s = pluralizefr(len(invitations))
    expiration_date = formats.date_format(invitations[0].expiration_date)
    return (
        f"Collaborateur{s} ajouté{s}||Pour rejoindre votre organisation, il suffira à "
        f"{pluralizefr(len(invitations), 'votre,vos')} collaborateur{s} de cliquer sur le lien d'activation "
        f"contenu dans l'e-mail avant le {expiration_date}."
    )


class BaseInviteUserView(UserPassesTestMixin, TemplateView):
    invitation_model = None
    form_class = None
    formset_class = None
    organization = None
    form_post_url = None
    back_url = None
    template_name = "invitations_views/create.html"

    def setup(self, request, *args, **kwargs):
        self.organization = getattr(request, "current_organization", None)
        if self.organization is None:
            raise PermissionDenied
        self.invitation_left = MAX_PENDING_INVITATION - self.organization.invitations.pending().count()
        return super().setup(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if self.invitation_left < 1:
            messages.error(request, f"Vous ne pouvez avoir plus de {MAX_PENDING_INVITATION} invitations.")
            return HttpResponseRedirect(self.back_url)

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        raise NotImplementedError

    def get_initial_data(self):
        return None

    def get_formset(self):
        formset = modelformset_factory(
            self.invitation_model,
            form=self.form_class,
            formset=self.formset_class,
            extra=1,
            max_num=self.invitation_left,
            absolute_max=self.invitation_left,
        )
        return formset(
            self.request.POST or None,
            initial=self.get_initial_data(),
            form_kwargs=self.get_form_kwargs(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["back_url"] = self.back_url
        context["form_post_url"] = self.form_post_url
        context["formset"] = self.get_formset()
        context["organization"] = self.organization
        return context

    def post(self, request, *args, **kwargs):
        formset = self.get_formset()
        if formset.is_valid():
            invitations = formset.save()

            for invitation in invitations:
                invitation.send()

            messages.success(
                request,
                _toast_invitation_sent(invitations),
                extra_tags="toast",
            )
            return redirect(self.back_url)
        return super().get(request, *args, **kwargs)


class InvitePrescriberView(BaseInviteUserView):
    invitation_model = PrescriberWithOrgInvitation
    form_class = PrescriberWithOrgInvitationForm
    formset_class = BasePrescriberWithOrgInvitationFormSet
    form_post_url = reverse_lazy("invitations_views:invite_prescriber_with_org")
    back_url = reverse_lazy("prescribers_views:members")

    def test_func(self):
        return self.request.from_prescriber

    def get_initial_data(self):
        request_invitation_form = signup_forms.PrescriberRequestInvitationForm(data=self.request.GET)
        if request_invitation_form.is_valid():
            # The prescriber has accepted the request for an invitation of an external user.
            # The form will be pre-filled with the new user information.
            return [
                {
                    "first_name": request_invitation_form.cleaned_data.get("first_name"),
                    "last_name": request_invitation_form.cleaned_data.get("last_name"),
                    "email": request_invitation_form.cleaned_data.get("email"),
                }
            ]
        return None

    def get_form_kwargs(self):
        return {"sender": self.request.user, "organization": self.organization}


def join_prescriber_organization(request, invitation_id):
    invitation = get_object_or_404(PrescriberWithOrgInvitation, pk=invitation_id)
    handle_prescriber_intivation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.organization.pk
    url = get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(url)


class InviteEmployerView(BaseInviteUserView):
    invitation_model = EmployerInvitation
    form_class = EmployerInvitationForm
    formset_class = BaseEmployerInvitationFormSet
    form_post_url = reverse_lazy("invitations_views:invite_employer")
    back_url = reverse_lazy("companies_views:members")

    def test_func(self):
        return self.request.from_employer

    def get_form_kwargs(self):
        return {"sender": self.request.user, "company": self.organization}


def join_company(request, invitation_id):
    invitation = get_object_or_404(EmployerInvitation, pk=invitation_id)
    handle_employer_invitation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.company.pk
    url = get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(url)


class InviteLaborInspectorView(BaseInviteUserView):
    invitation_model = LaborInspectorInvitation
    form_class = LaborInspectorInvitationForm
    formset_class = BaseLaborInspectorInvitationFormSet
    form_post_url = reverse_lazy("invitations_views:invite_labor_inspector")
    back_url = reverse_lazy("institutions_views:members")

    def test_func(self):
        return self.request.user.is_labor_inspector

    def get_form_kwargs(self):
        return {"sender": self.request.user, "institution": self.organization}


def join_institution(request, invitation_id):
    invitation = get_object_or_404(LaborInspectorInvitation, pk=invitation_id)
    handle_labor_inspector_invitation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.institution.pk
    return redirect("dashboard:index")
