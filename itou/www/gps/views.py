from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url
from itou.www.gps.forms import GpsUserSearchForm, MembershipsFiltersForm


def is_allowed_to_use_gps(user):
    return user.is_employer or user.is_prescriber


def is_allowed_to_use_gps_advanced_features(user):
    return user.is_employer or user.is_prescriber_with_authorized_org


@login_required
@check_user(is_allowed_to_use_gps)
def my_groups(request, template_name="gps/my_groups.html"):
    memberships = (
        FollowUpGroupMembership.objects.filter(member=request.user)
        .filter(is_active=True)
        .annotate(nb_members=Count("follow_up_group__members"))
        .order_by("-created_at")
        .select_related("follow_up_group", "follow_up_group__beneficiary", "member")
        .prefetch_related("follow_up_group__members")
    )
    filters_form = MembershipsFiltersForm(memberships_qs=memberships, data=request.GET or None)

    if filters_form.is_valid():
        memberships = filters_form.filter()

    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=10)

    context = {
        "back_url": reverse("dashboard:index"),
        "filters_form": filters_form,
        "memberships_page": memberships_page,
        "can_use_gps_advanced_features": is_allowed_to_use_gps_advanced_features(request.user),
    }

    return render(request, "gps/includes/memberships_results.html" if request.htmx else template_name, context)


@login_required
@check_user(is_allowed_to_use_gps_advanced_features)
def join_group(request, template_name="gps/join_group.html"):
    form = GpsUserSearchForm(data=request.POST or None)

    my_groups_url = reverse("gps:my_groups")
    back_url = get_safe_url(request, "back_url", my_groups_url)

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        is_referent = form.cleaned_data["is_referent"]

        FollowUpGroup.objects.follow_beneficiary(beneficiary=user, user=request.user, is_referent=is_referent)

        return HttpResponseRedirect(my_groups_url)

    context = {
        "form": form,
        "reset_url": back_url,
    }

    return render(request, template_name, context)


@login_required
@check_user(is_allowed_to_use_gps)
def leave_group(request, group_id):
    membership = (
        FollowUpGroupMembership.objects.filter(member=request.user).filter(follow_up_group__id=group_id).first()
    )

    if membership:
        membership.is_active = False
        membership.save()

    return HttpResponseRedirect(reverse("gps:my_groups"))


@login_required
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
    template_name = "users/details.html"
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
            .order_by("-is_referent")
            .select_related("follow_up_group", "member")
        )

        org_department = self.request.current_organization.department
        matomo_option = org_department if org_department in self.get_live_department_codes() else None
        back_url = get_safe_url(self.request, "back_url", fallback_url=reverse_lazy("gps:my_groups"))

        membership = next(m for m in gps_memberships if m.member == self.request.user)

        context = context | {
            "back_url": back_url,
            "gps_memberships": gps_memberships,
            "is_referent": membership.is_referent,
            "matomo_custom_title": "Profil GPS",
            "profile": self.object.jobseeker_profile,
            "render_advisor_matomo_option": matomo_option,
            "matomo_option": "coordonnees-conseiller-" + (matomo_option if matomo_option else "ailleurs"),
        }

        return context
