from django.core.exceptions import BadRequest
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy

from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.perms.institution import get_current_institution_or_404


def member_list(request, template_name="institutions/members.html"):
    """
    List members of an institution.
    """
    institution = get_current_institution_or_404(request)

    members = (
        institution.institutionmembership_set.active().select_related("user").all().order_by("-is_admin", "joined_at")
    )
    members_stats = members.aggregate(
        total_count=Count("pk"),
        admin_count=Count("pk", filter=Q(is_admin=True)),
    )

    pending_invitations = None
    # Institution members can only be labor inspectors for the moment,
    # but this is likely to change in the future.
    if request.user.is_labor_inspector:
        pending_invitations = institution.invitations.pending()

    context = {
        "institution": institution,
        "members": members,
        "members_stats": members_stats,
        "pending_invitations": pending_invitations,
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_labor_inspector)
def deactivate_member(request, public_id, template_name="institutions/deactivate_member.html"):
    user = get_object_or_404(User, public_id=public_id)
    return deactivate_org_member(
        request,
        user.id,
        success_url=reverse_lazy("institutions_views:members"),
        template_name=template_name,
    )


@check_user(lambda user: user.is_labor_inspector)
def update_admin_role(request, action, public_id, template_name="institutions/update_admins.html"):
    if action not in ["add", "remove"]:
        raise BadRequest
    user = get_object_or_404(User, public_id=public_id)
    return update_org_admin_role(
        request,
        action,
        user.id,
        success_url=reverse("institutions_views:members"),
        template_name=template_name,
    )
