"""
Functions used in organization views.
"""

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.generic import ListView

from itou.utils.pagination import ItouPaginator
from itou.www.invitations_views.views import MAX_PENDING_INVITATION


class BaseMemberList(UserPassesTestMixin, ListView):
    paginate_by = 50  # Most organizations will have only one page
    paginator_class = ItouPaginator

    def setup(self, request, *args, **kwargs):
        # test_func is called in super().dispatch so we can jobseeker here and current_organization won't exist
        self.organization = getattr(request, "current_organization", None)
        if self.organization is None:
            raise PermissionDenied
        super().setup(request, *args, **kwargs)

    def get_queryset(self):
        return (
            self.organization.memberships.select_related("user")
            .all()
            .order_by("user__last_name", "user__first_name", "pk")
        )

    def get_invitation_url(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        members_stats = self.get_queryset().aggregate(
            total_count=Count("pk"),
            admin_count=Count("pk", filter=Q(is_admin=True)),
        )
        pending_invitations = self.organization.invitations.pending()

        context["members_stats"] = members_stats
        context["pending_invitations"] = pending_invitations
        context["invitation_url"] = (
            self.get_invitation_url() if len(pending_invitations) < MAX_PENDING_INVITATION else None
        )
        context["active_admin_members"] = self.organization.active_admin_members
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
            request,
            f"{membership.user.get_inverted_full_name()} a été retiré(e) des membres actifs de cette structure.",
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
            request,
            f"{membership.user.get_inverted_full_name()} a été {action_label} administrateurs de cette structure.",
        )
        return HttpResponseRedirect(success_url)

    context = {
        "action": action,
        "structure": request.current_organization,
        "target_member": membership.user,
    }
    return render(request, template_name, context)
