from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.sessions import kill_sessions_for_user
from itou.utils.urls import get_safe_url
from itou.www.prescribers_views.forms import EditPrescriberOrganizationForm


def card(request, org_id, template_name="prescribers/card.html"):
    """
    Prescriber organization's card (or "Fiche" in French).
    """
    prescriber_org = get_object_or_404(PrescriberOrganization, pk=org_id, is_authorized=True)
    back_url = get_safe_url(request, "back_url")
    context = {"prescriber_org": prescriber_org, "back_url": back_url}
    return render(request, template_name, context)


@login_required
def edit_organization(request, template_name="prescribers/edit_organization.html"):
    """
    Edit a prescriber organization.
    """
    organization = get_current_org_or_404(request)

    form = EditPrescriberOrganizationForm(instance=organization, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form, "organization": organization}
    return render(request, template_name, context)


@login_required
def members(request, template_name="prescribers/members.html"):
    """
    List members of a prescriber organization.
    """
    organization = get_current_org_or_404(request)

    members = (
        organization.prescribermembership_set.filter(is_active=True)
        .select_related("user")
        .all()
        .order_by("-is_admin", "joined_at")
    )
    pending_invitations = organization.invitations.filter(accepted=False).all().order_by("sent_at")

    deactivated_members = (
        organization.prescribermembership_set.filter(is_active=False)
        .select_related("user")
        .all()
        .order_by("updated_at")
    )

    context = {
        "organization": organization,
        "members": members,
        "pending_invitations": pending_invitations,
        "deactivated_members": deactivated_members,
    }
    return render(request, template_name, context)


@login_required
@require_POST
def toggle_membership(request, membership_id, template_name="prescribers/members.html"):
    """
    Deactivate (or later reactivate) a member of a structure
    """
    organization = get_current_org_or_404(request)
    user = request.user
    membership = PrescriberMembership.objects.get(pk=membership_id)

    if user != membership.user and user in organization.active_admin_members:
        membership.toggleUserMembership(user)
        membership.save()

        if not membership.is_active:
            messages.success(request, _("Le collaborateur a été retiré des membres actifs de cette structure."))
            organization.new_member_deactivation_email(membership.user).send()
            kill_sessions_for_user(membership.user.pk)
        else:
            messages.success(request, _("Le collaborateur est à nouveau un membre actif de cette structure."))
            organization.new_member_activation_email(membership.user).send()
    else:
        raise PermissionDenied

    return HttpResponseRedirect(reverse_lazy("prescribers_views:members"))
