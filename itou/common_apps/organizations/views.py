"""
Functions used in organization views.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied


def deactivate_org_member(request, target_member):
    if not request.is_current_organization_admin or target_member not in request.current_organization.active_members:
        raise PermissionDenied

    membership = request.current_organization.memberships.get(user=target_member)

    if request.method == "POST":
        if request.user != target_member and request.is_current_organization_admin:
            if membership.is_active:
                # Deactivate the membership without deleting it.
                membership.deactivate_membership_by_user(request.user)
                membership.save()
                messages.success(
                    request, f"{target_member.get_full_name()} a été retiré(e) des membres actifs de cette structure."
                )
                request.current_organization.member_deactivation_email(membership.user).send()
        else:
            raise PermissionDenied
        return True

    return False


def update_org_admin_role(request, target_member, action):
    if not request.is_current_organization_admin or target_member not in request.current_organization.active_members:
        raise PermissionDenied

    membership = request.current_organization.memberships.get(user=target_member)

    if request.method == "POST":
        if request.user != target_member and request.is_current_organization_admin and membership.is_active:
            if action == "add":
                membership.set_admin_role(is_admin=True, updated_by=request.user)
                messages.success(
                    request, f"{target_member.get_full_name()} a été ajouté(e) aux administrateurs de cette structure."
                )
                request.current_organization.add_admin_email(target_member).send()
            if action == "remove":
                membership.set_admin_role(is_admin=False, updated_by=request.user)
                messages.success(
                    request, f"{target_member.get_full_name()} a été retiré(e) des administrateurs de cette structure."
                )
                request.current_organization.remove_admin_email(target_member).send()
            membership.save()
        else:
            raise PermissionDenied
        return True

    return False
