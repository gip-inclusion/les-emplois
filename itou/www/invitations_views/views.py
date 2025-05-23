from urllib.parse import urlencode

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.utils import formats, safestring

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
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.templatetags.str_filters import pluralizefr
from itou.www.invitations_views.forms import (
    EmployerInvitationFormSet,
    LaborInspectorInvitationFormSet,
    NewUserInvitationForm,
    PrescriberWithOrgInvitationFormSet,
)
from itou.www.invitations_views.helpers import (
    handle_employer_invitation,
    handle_labor_inspector_invitation,
    handle_prescriber_intivation,
)
from itou.www.signup import forms as signup_forms


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
    params = {
        "user_kind": invitation_type,
        "user_email": invitation.email,
        "channel": ProConnectChannel.INVITATION.value,
        "previous_url": request.get_full_path(),
        "next_url": invitation.acceptance_url_for_existing_user,
    }
    pro_connect_url = (
        f"{reverse('pro_connect:authorize')}?{urlencode(params)}" if settings.PRO_CONNECT_BASE_URL else None
    )
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
        login_url = reverse(f"login:{invitation.USER_KIND}")
        next_step_url = f"{login_url}?next={invitation.acceptance_url_for_existing_user}"
        return redirect(next_step_url)

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


def invite_prescriber_with_org(request, template_name="invitations_views/create.html"):
    organization = get_current_org_or_404(request)
    form_kwargs = {"sender": request.user, "organization": organization}

    # Initial data can be passed by GET params to ease invitation of new members
    request_invitation_form = signup_forms.PrescriberRequestInvitationForm(data=request.GET)
    if request_invitation_form.is_valid():
        # The prescriber has accepted the request for an invitation of an external user.
        # The form will be pre-filled with the new user information.
        initial_data = [
            {
                "first_name": request_invitation_form.cleaned_data.get("first_name"),
                "last_name": request_invitation_form.cleaned_data.get("last_name"),
                "email": request_invitation_form.cleaned_data.get("email"),
            }
        ]
    else:
        initial_data = None

    formset = PrescriberWithOrgInvitationFormSet(
        data=request.POST or None, initial=initial_data, form_kwargs=form_kwargs
    )
    if request.POST:
        if formset.is_valid():
            # We don't need atomicity here (invitations are independent)
            invitations = formset.save()

            for invitation in invitations:
                invitation.send()

            messages.success(
                request,
                _toast_invitation_sent(invitations),
                extra_tags="toast",
            )
            return redirect(request.path)

    form_post_url = reverse("invitations_views:invite_prescriber_with_org")
    back_url = reverse("prescribers_views:members")
    context = {"back_url": back_url, "form_post_url": form_post_url, "formset": formset, "organization": organization}

    return render(request, template_name, context)


def join_prescriber_organization(request, invitation_id):
    invitation = get_object_or_404(PrescriberWithOrgInvitation, pk=invitation_id)
    handle_prescriber_intivation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.organization.pk
    url = get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(url)


def invite_employer(request, template_name="invitations_views/create.html"):
    form_post_url = reverse("invitations_views:invite_employer")
    back_url = reverse("companies_views:members")
    company = get_current_company_or_404(request)
    form_kwargs = {"sender": request.user, "company": company}
    formset = EmployerInvitationFormSet(data=request.POST or None, form_kwargs=form_kwargs)
    if request.POST:
        if formset.is_valid():
            # We don't need atomicity here (invitations are independent)
            invitations = formset.save()

            for invitation in invitations:
                invitation.send()

            messages.success(
                request,
                _toast_invitation_sent(invitations),
                extra_tags="toast",
            )
            return redirect(back_url)

    context = {"back_url": back_url, "form_post_url": form_post_url, "formset": formset, "organization": company}

    return render(request, template_name, context)


def join_company(request, invitation_id):
    invitation = get_object_or_404(EmployerInvitation, pk=invitation_id)
    handle_employer_invitation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.company.pk
    url = get_adapter(request).get_login_redirect_url(request)
    return HttpResponseRedirect(url)


def invite_labor_inspector(request, template_name="invitations_views/create.html"):
    institution = get_current_institution_or_404(request)
    form_kwargs = {"sender": request.user, "institution": institution}
    formset = LaborInspectorInvitationFormSet(data=request.POST or None, form_kwargs=form_kwargs)
    if request.POST:
        if formset.is_valid():
            # We don't need atomicity here (invitations are independent)
            invitations = formset.save()

            for invitation in invitations:
                invitation.send()

            messages.success(
                request,
                _toast_invitation_sent(invitations),
                extra_tags="toast",
            )
            return redirect(request.path)

    form_post_url = reverse("invitations_views:invite_labor_inspector")
    back_url = reverse("institutions_views:members")
    context = {"back_url": back_url, "form_post_url": form_post_url, "formset": formset, "organization": institution}

    return render(request, template_name, context)


def join_institution(request, invitation_id):
    invitation = get_object_or_404(LaborInspectorInvitation, pk=invitation_id)
    handle_labor_inspector_invitation(invitation, request)
    request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = invitation.institution.pk
    return redirect("dashboard:index")
