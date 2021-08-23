"""
Functions used in organization views.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied


def deactivate_org_member(request, organization, target_member):
    current_user = request.user
    user_is_admin = organization.has_admin(current_user)

    if not user_is_admin or target_member not in organization.active_members:
        raise PermissionDenied

    membership = organization.memberships.get(user=target_member)

    if request.method == "POST":
        if current_user != target_member and user_is_admin:
            if membership.is_active:
                # Only membership is modified
                membership.deactivate_membership_by_user(current_user)
                membership.save()
                messages.success(
                    request,
                    "%(name)s a été retiré(e) des membres actifs de cette structure."
                    % {"name": target_member.get_full_name()},
                )
                organization.member_deactivation_email(membership.user).send()
        else:
            raise PermissionDenied
        return True

    return False
