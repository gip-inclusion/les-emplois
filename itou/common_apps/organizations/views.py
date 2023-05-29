"""
Functions used in organization views.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied


def deactivate_org_member(request, organization, target_member):
    user_is_admin = organization.has_admin(request.user)

    if not user_is_admin or target_member not in organization.active_members:
        raise PermissionDenied

    membership = organization.memberships.get(user=target_member)

    if request.method == "POST":
        if request.user != target_member and user_is_admin:
            if membership.is_active:
                # Deactivate the membership without deleting it.
                membership.deactivate_membership_by_user(request.user)
                membership.save()
                messages.success(
                    request, f"{target_member.get_full_name()} a été retiré(e) des membres actifs de cette structure."
                )
                organization.member_deactivation_email(membership.user).send()
        else:
            raise PermissionDenied
        return True

    return False


def update_org_admin_role(request, organization, target_member, action):
    user_is_admin = organization.has_admin(request.user)

    if not user_is_admin or target_member not in organization.active_members:
        raise PermissionDenied

    membership = organization.memberships.get(user=target_member)

    if request.method == "POST":
        if request.user != target_member and user_is_admin and membership.is_active:
            if action == "add":
                membership.set_admin_role(is_admin=True, updated_by=request.user)
                messages.success(
                    request, f"{target_member.get_full_name()} a été ajouté(e) aux administrateurs de cette structure."
                )
                organization.add_admin_email(target_member).send()
            if action == "remove":
                membership.set_admin_role(is_admin=False, updated_by=request.user)
                messages.success(
                    request, f"{target_member.get_full_name()} a été retiré(e) des administrateurs de cette structure."
                )
                organization.remove_admin_email(target_member).send()
            membership.save()
        else:
            raise PermissionDenied
        return True

    return False
