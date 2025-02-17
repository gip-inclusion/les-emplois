import urllib.parse

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import DetailView

from itou.gps.grist import log_contact_info_display
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url
from itou.www.gps.forms import MembershipsFiltersForm


def is_allowed_to_use_gps(user):
    return user.is_employer or user.is_prescriber


def is_allowed_to_use_gps_advanced_features(user):
    return user.is_employer or user.is_prescriber_with_authorized_org


def in_gard(request):
    return getattr(request.current_organization, "department", None) == "30"


@check_user(is_allowed_to_use_gps)
def group_list(request, current, template_name="gps/group_list.html"):
    qs = FollowUpGroupMembership.objects.filter(member=request.user)

    if current:
        qs = qs.filter(is_active=True, ended_at=None)
    else:
        qs = qs.exclude(ended_at=None)

    memberships = (
        qs.annotate(nb_members=Count("follow_up_group__members"))
        .order_by("-created_at")
        .select_related("follow_up_group", "follow_up_group__beneficiary", "member")
        .prefetch_related(
            Prefetch(
                "follow_up_group__memberships",
                queryset=FollowUpGroupMembership.objects.filter(is_referent=True)[:1],
                to_attr="referent",
            ),
        )
    )
    filters_form = MembershipsFiltersForm(memberships_qs=memberships, data=request.GET or None)

    if filters_form.is_valid():
        memberships = filters_form.filter()

    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=50)

    context = {
        "filters_form": filters_form,
        "memberships_page": memberships_page,
        "active_memberships": current,
    }

    context["request_new_beneficiary_form_url"] = (
        "https://formulaires.gps.inclusion.gouv.fr/ajouter-usager?"
        + urllib.parse.urlencode(
            {
                "user_name": request.user.get_full_name(),
                "user_id": request.user.pk,
                "user_email": request.user.email,
                "user_organization_name": getattr(request.current_organization, "display_name", ""),
                "user_organization_id": getattr(request.current_organization, "pk", ""),
                "success_url": request.build_absolute_uri(),
            }
        )
    )

    return render(request, "gps/includes/memberships_results.html" if request.htmx else template_name, context)


@check_user(is_allowed_to_use_gps)
def leave_group(request, group_id):
    membership = (
        FollowUpGroupMembership.objects.filter(member=request.user).filter(follow_up_group__id=group_id).first()
    )

    if membership:
        membership.is_active = False
        membership.save()

    return HttpResponseRedirect(reverse("gps:group_list"))


@check_user(is_allowed_to_use_gps)
def toggle_referent(request, group_id):
    membership = (
        FollowUpGroupMembership.objects.filter(member=request.user)
        .filter(follow_up_group__id=group_id)
        .select_related("follow_up_group__beneficiary")
        .first()
    )

    if membership:
        membership.is_referent = not membership.is_referent
        membership.save()

    return HttpResponseRedirect(reverse("gps:user_details", args=(membership.follow_up_group.beneficiary.public_id,)))


class UserDetailsView(LoginRequiredMixin, DetailView):
    model = User
    queryset = User.objects.select_related("follow_up_group", "jobseeker_profile").prefetch_related(
        "follow_up_group__memberships"
    )
    template_name = "gps/user_details.html"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"
    context_object_name = "beneficiary"

    def setup(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (
            is_allowed_to_use_gps(request.user)
            and FollowUpGroupMembership.objects.filter(
                follow_up_group__beneficiary__public_id=kwargs["public_id"],
                member=request.user,
                is_active=True,
            ).exists()
        ):
            raise PermissionDenied("Votre utilisateur n'est pas autorisé à accéder à ces informations.")
        super().setup(request, *args, **kwargs)

    def get_live_department_codes(self):
        """For the initial release only some departments have the feature"""
        return [
            "30",  # Le Gard
            "55",  # La Meuse
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        gps_memberships = (
            FollowUpGroupMembership.objects.with_members_organizations_names()
            .filter(follow_up_group=self.object.follow_up_group)
            .filter(is_active=True)
            .order_by("-created_at")
            .select_related("follow_up_group", "member")
        )

        org_department = getattr(self.request.current_organization, "department", None)
        matomo_option = org_department if org_department in self.get_live_department_codes() else None
        back_url = get_safe_url(self.request, "back_url", fallback_url=reverse_lazy("gps:group_list"))

        membership = next(m for m in gps_memberships if m.member == self.request.user)

        request_new_participant_form_url = (
            "https://formulaires.gps.inclusion.gouv.fr/ajouter-intervenant?"
            + urllib.parse.urlencode(
                {
                    "user_name": self.request.user.get_full_name(),
                    "user_id": self.request.user.pk,
                    "user_email": self.request.user.email,
                    "user_organization_name": getattr(self.request.current_organization, "display_name", ""),
                    "user_organization_id": getattr(self.request.current_organization, "pk", ""),
                    "user_type": self.request.user.kind,
                    "beneficiary_name": self.object.get_full_name(),
                    "beneficiary_id": self.object.pk,
                    "beneficiary_email": self.object.email,
                    "success_url": self.request.build_absolute_uri(),
                }
            )
        )

        context = context | {
            "back_url": back_url,
            "gps_memberships": gps_memberships,
            "is_referent": membership.is_referent,
            "matomo_custom_title": "Profil GPS",
            "profile": self.object.jobseeker_profile,
            "render_advisor_matomo_option": matomo_option,
            "matomo_option": "coordonnees-conseiller-" + (matomo_option if matomo_option else "ailleurs"),
            "request_new_participant_form_url": request_new_participant_form_url,
        }

        return context


@require_POST
@check_user(is_allowed_to_use_gps)
def display_contact_info(request, group_id, target_participant_public_id, mode):
    template_name = {
        "email": "gps/includes/member_email.html",
        "phone": "gps/includes/member_phone.html",
    }.get(mode, None)
    if not template_name:
        raise ValueError("Invalid mode: %s", mode)

    follow_up_group = get_object_or_404(FollowUpGroup.objects.filter(members=request.user), pk=group_id)
    target_participant = get_object_or_404(
        User.objects.filter(follow_up_groups__follow_up_group_id=group_id),
        public_id=target_participant_public_id,
    )
    log_contact_info_display(request.user, follow_up_group, target_participant, mode)
    return render(request, template_name, {"member": target_participant})
