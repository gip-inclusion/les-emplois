"""
Functions used in organization views.
"""

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.shortcuts import get_object_or_404


def deactivate_org_member(request, target_member):
    if not request.is_current_organization_admin or request.user == target_member:
        raise PermissionDenied

    membership = get_object_or_404(request.current_organization.memberships, user=target_member, is_active=True)

    if request.method == "POST":
        if membership.is_active:
            request.current_organization.deactivate_membership(membership, updated_by=request.user)
            messages.success(
                request, f"{target_member.get_full_name()} a été retiré(e) des membres actifs de cette structure."
            )
        return True

    return False


def update_org_admin_role(request, target_member, action):
    if not request.is_current_organization_admin or target_member == request.user:
        raise PermissionDenied

    try:
        membership = request.current_organization.memberships.select_related("user").get(
            user=target_member,
            is_active=True,
        )
    except ObjectDoesNotExist:
        raise PermissionDenied

    if request.method == "POST":
        match action:
            case "add":
                admin = True
                action_label = "ajouté(e) aux"
            case "remove":
                admin = False
                action_label = "retiré(e) des"
            case _:
                raise ValueError(f"Unknown {action=}")
        request.current_organization.set_admin_role(membership, admin, updated_by=request.user)
        messages.success(
            request, f"{target_member.get_full_name()} a été {action_label} administrateurs de cette structure."
        )
        return True

    return False
