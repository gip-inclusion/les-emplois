from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.perms.prescriber import get_current_org_or_404
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
    pending_invitations = organization.invitations.pending()

    context = {
        "organization": organization,
        "members": members,
        "pending_invitations": pending_invitations,
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="prescribers/deactivate_member.html"):
    organization = get_current_org_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)
    user_is_admin = organization.has_admin(user)

    if not user_is_admin:
        raise PermissionDenied

    if target_member not in organization.active_members:
        raise PermissionDenied

    membership = target_member.prescribermembership_set.get(organization=organization)

    if request.method == "POST":
        if user != target_member and user_is_admin:
            if membership.is_active:
                membership.toggle_user_membership(user)
                membership.save()
                messages.success(
                    request,
                    _("%(name)s a été retiré(e) des membres actifs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                organization.member_deactivation_email(membership.user).send()
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("prescribers_views:members"))

    context = {
        "structure": organization,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="prescribers/update_admins.html"):
    organization = get_current_org_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)
    user_is_admin = organization.has_admin(user)

    if not user_is_admin:
        raise PermissionDenied

    if target_member not in organization.active_members:
        raise PermissionDenied

    membership = target_member.prescribermembership_set.get(organization=organization)

    if request.method == "POST":
        if user != target_member and user_is_admin and membership.is_active:
            if action == "add":
                membership.set_admin_role(True, user)
                messages.success(
                    request,
                    _("%(name)s a été ajouté(e) aux administrateurs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                organization.add_admin_email(target_member).send()
            if action == "remove":
                membership.set_admin_role(False, user)
                messages.success(
                    request,
                    _("%(name)s a été retiré(e) des administrateurs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                organization.remove_admin_email(target_member).send()
            membership.save()
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("prescribers_views:members"))

    context = {
        "action": action,
        "structure": organization,
        "target_member": target_member,
    }

    return render(request, template_name, context)
