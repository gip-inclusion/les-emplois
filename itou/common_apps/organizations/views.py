"""
Functions used in organization views.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.generic import ListView


class BaseMemberList(ListView):
    def get_queryset(self):
        memberships = getattr(self.organization, self.membership_related_name)
        return memberships.active().select_related("user").all().order_by("joined_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        members_stats = self.get_queryset().aggregate(
            total_count=Count("pk"),
            admin_count=Count("pk", filter=Q(is_admin=True)),
        )
        pending_invitations = self.organization.invitations.pending()

        context[self.context_object_name] = self.organization
        context["members_stats"] = members_stats
        context["pending_invitations"] = pending_invitations
        return context


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


def update_org_admin_role(request, action, user_id, *, success_url, template_name):
    if not request.is_current_organization_admin or request.user.pk == user_id:
        raise PermissionDenied

    membership = get_object_or_404(
        request.current_organization.memberships.select_related("user"),
        user_id=user_id,
        is_active=True,
    )

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
            request, f"{membership.user.get_full_name()} a été {action_label} administrateurs de cette structure."
        )
        return HttpResponseRedirect(success_url)

    context = {
        "action": action,
        "structure": request.current_organization,
        "target_member": membership.user,
    }
    return render(request, template_name, context)
