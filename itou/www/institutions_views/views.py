from django.core.exceptions import BadRequest
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy

from itou.common_apps.organizations.views import BaseMemberList, deactivate_org_member, update_org_admin_role
from itou.users.models import User
from itou.utils.auth import check_user


class MemberList(BaseMemberList):
    template_name = "institutions/members.html"

    def test_func(self):
        return self.request.user.is_labor_inspector

    def get_invitation_url(self):
        return reverse("invitations_views:invite_labor_inspector")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_url"] = "institutions_views"
        return context


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
