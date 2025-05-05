from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import BadRequest, PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.auth import check_user
from itou.utils.perms.prescriber import get_current_org_or_404
from itou.utils.urls import get_safe_url
from itou.www.prescribers_views.forms import EditPrescriberOrganizationForm


@login_not_required
def card(request, org_id, template_name="prescribers/card.html"):
    prescriber_org = get_object_or_404(
        PrescriberOrganization,
        pk=org_id,
        authorization_status=PrescriberAuthorizationStatus.VALIDATED,
    )
    back_url = get_safe_url(request, "back_url")
    context = {
        "prescriber_org": prescriber_org,
        "back_url": back_url,
        "matomo_custom_title": "Fiche de l'organisation prescriptrice",
    }
    return render(request, template_name, context)


def edit_organization(request, template_name="prescribers/edit_organization.html"):
    organization = get_current_org_or_404(request)
    if not organization.has_admin(request.user):
        raise PermissionDenied

    back_url = get_safe_url(request, "back_url", reverse("dashboard:index"))
    form = EditPrescriberOrganizationForm(instance=organization, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            form.save()
            messages.success(request, "Mise à jour effectuée !", extra_tags="toast")
            return HttpResponseRedirect(back_url)
        except GeocodingDataError:
            messages.error(request, "L'adresse semble erronée. Veuillez la corriger avant de pouvoir « Enregistrer ».")

    context = {"form": form, "organization": organization, "back_url": back_url}
    return render(request, template_name, context)


@check_user(lambda user: user.is_prescriber)
def overview(request, template_name="prescribers/overview.html"):
    organization = get_current_org_or_404(request)
    if not organization.is_authorized:
        raise Http404

    context = {
        "organization": organization,
        "can_edit": organization.has_admin(request.user),
    }
    return render(request, template_name, context)


def member_list(request, template_name="prescribers/members.html"):
    """
    List members of a prescriber organization.
    """
    organization = get_current_org_or_404(request)

    members = (
        organization.prescribermembership_set.active().select_related("user").all().order_by("-is_admin", "joined_at")
    )
    members_stats = members.aggregate(
        total_count=Count("pk"),
        admin_count=Count("pk", filter=Q(is_admin=True)),
    )
    pending_invitations = organization.invitations.pending()

    context = {
        "organization": organization,
        "members": members,
        "members_stats": members_stats,
        "pending_invitations": pending_invitations,
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_prescriber)
def deactivate_member(request, public_id, template_name="prescribers/deactivate_member.html"):
    user = get_object_or_404(User, public_id=public_id)
    return deactivate_org_member(
        request,
        user.id,
        success_url=reverse("prescribers_views:members"),
        template_name=template_name,
    )


@check_user(lambda user: user.is_prescriber)
def update_admin_role(request, action, public_id, template_name="prescribers/update_admins.html"):
    if action not in ["add", "remove"]:
        raise BadRequest
    user = get_object_or_404(User, public_id=public_id)
    return update_org_admin_role(
        request,
        action,
        user.id,
        success_url=reverse("prescribers_views:members"),
        template_name=template_name,
    )


def list_accredited_organizations(request, template_name="prescribers/list_accredited_organizations.html"):
    """
    List organizations accredited by a departmental council ("Conseil Départemental").
    """
    prescriber_org = get_current_org_or_404(request)

    required_permissions = [
        prescriber_org.is_authorized,
        prescriber_org.kind == PrescriberOrganizationKind.DEPT,
        request.is_current_organization_admin,
    ]

    if not all(required_permissions):
        raise PermissionDenied

    accredited_orgs = PrescriberOrganization.objects.get_accredited_orgs_for(
        prescriber_org
    ).prefetch_active_memberships()

    context = {
        "prescriber_org": prescriber_org,
        "accredited_orgs": accredited_orgs,
        "back_url": get_safe_url(request, "back_url"),
    }
    return render(request, template_name, context)
