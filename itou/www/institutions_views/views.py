from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy

from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.users.models import User
from itou.utils.perms.institution import get_current_institution_or_404


@login_required
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
        pending_invitations = institution.labor_inspectors_invitations.pending()

    context = {
        "institution": institution,
        "members": members,
        "members_stats": members_stats,
        "pending_invitations": pending_invitations,
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="institutions/deactivate_member.html"):
    institution = get_current_institution_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if deactivate_org_member(request=request, target_member=target_member):
        return HttpResponseRedirect(reverse_lazy("institutions_views:members"))

    context = {
        "structure": institution,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="institutions/update_admins.html"):
    institution = get_current_institution_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if update_org_admin_role(request=request, target_member=target_member, action=action):
        return HttpResponseRedirect(reverse_lazy("institutions_views:members"))

    context = {
        "action": action,
        "structure": institution,
        "target_member": target_member,
    }

    return render(request, template_name, context)
