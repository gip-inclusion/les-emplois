"""
Functions used in organization views.
"""

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render


def deactivate_org_member(request, user_id, *, success_url, template_name):
    if not request.is_current_organization_admin or request.user.pk == user_id:
        raise PermissionDenied

    membership = get_object_or_404(
        request.current_organization.memberships.select_related("user"),
        user_id=user_id,
        is_active=True,
    )

    if request.method == "POST":
        request.current_organization.deactivate_membership(membership, updated_by=request.user)
        messages.success(
            request, f"{membership.user.get_full_name()} a été retiré(e) des membres actifs de cette structure."
        )
        return HttpResponseRedirect(success_url)

    context = {
        "structure": request.current_organization,
        "target_member": membership.user,
    }

    return render(request, template_name, context)


def update_org_admin_role(request, target_member, action):
    if not request.is_current_organization_admin or target_member == request.user:
        raise PermissionDenied

    try:
        membership = request.current_organization.memberships.get(user=target_member, is_active=True)
    except ObjectDoesNotExist:
        raise PermissionDenied

    if request.method == "POST":
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
        return True

    return False
