from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy

from itou.users.models import User
from itou.utils.perms.institution import get_current_institution_or_404


@login_required
def member_list(request, template_name="institutions/members.html"):
    """
    List members of an institution.
    """
    institution = get_current_institution_or_404(request)

    members = (
        institution.institutionmembership_set.filter(is_active=True)
        .select_related("user")
        .all()
        .order_by("-is_admin", "joined_at")
    )

    pending_invitations = None
    # Institution members can only be labor inspectors for the moment,
    # but this is likely to change in the future.
    if request.user.is_labor_inspector:
        pending_invitations = institution.labor_inspectors_invitations.pending()

    context = {
        "institution": institution,
        "members": members,
        "pending_invitations": pending_invitations,
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="institutions/deactivate_member.html"):
    institution = get_current_institution_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)
    user_is_admin = institution.has_admin(user)

    if not user_is_admin:
        raise PermissionDenied

    if target_member not in institution.active_members:
        raise PermissionDenied

    membership = target_member.institutionmembership_set.get(institution=institution)

    if request.method == "POST":
        if user != target_member and user_is_admin:
            if membership.is_active:
                # Only membership is modified
                membership.deactivate_membership_by_user(user)
                membership.save()
                messages.success(
                    request,
                    "%(name)s a été retiré(e) des membres actifs de cette structure."
                    % {"name": target_member.get_full_name()},
                )
                institution.member_deactivation_email(membership.user).send()
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("institutions_views:members"))

    context = {
        "structure": institution,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="institutions/update_admins.html"):
    institution = get_current_institution_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)
    user_is_admin = institution.has_admin(user)

    if not user_is_admin:
        raise PermissionDenied

    if target_member not in institution.active_members:
        raise PermissionDenied

    membership = target_member.institutionmembership_set.get(institution=institution)

    if request.method == "POST":
        if user != target_member and user_is_admin and membership.is_active:
            if action == "add":
                membership.set_admin_role(True, user)
                messages.success(
                    request,
                    "%(name)s a été ajouté(e) aux administrateurs de cette structure."
                    % {"name": target_member.get_full_name()},
                )
                institution.add_admin_email(target_member).send()
            if action == "remove":
                membership.set_admin_role(False, user)
                messages.success(
                    request,
                    "%(name)s a été retiré(e) des administrateurs de cette structure."
                    % {"name": target_member.get_full_name()},
                )
                institution.remove_admin_email(target_member).send()
            membership.save()
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("institutions_views:members"))

    context = {
        "action": action,
        "structure": institution,
        "target_member": target_member,
    }

    return render(request, template_name, context)
