from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy
from django.views.generic import DetailView

from itou.gps.models import FollowUpGroupMembership
from itou.users.models import User
from itou.utils.urls import get_safe_url
from itou.www.gps.views import is_allowed_to_use_gps


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
        if request.user.is_authenticated and not is_allowed_to_use_gps(request.user):
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

        context = context | {
            "back_url": back_url,
            "gps_memberships": gps_memberships,
            "matomo_custom_title": "Profil GPS",
            "profile": self.object.jobseeker_profile,
            "render_advisor_matomo_option": matomo_option,
            "matomo_option": "coordonnees-conseiller-" + (matomo_option if matomo_option else "ailleurs"),
        }

        return context
