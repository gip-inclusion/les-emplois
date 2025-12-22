import logging

from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView

from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import NexusUser


logger = logging.getLogger(__name__)


class NexusMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_employer or self.request.user.is_prescriber

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        # Retrieve user data from nexus ressources
        self.service_users = NexusUser.objects.filter(
            email=self.request.user.email, source__in=Service.activable()
        ).prefetch_related("memberships__structure")
        self.activated_services_with_memberships = {}
        for service_user in self.service_users:
            self.activated_services_with_memberships[service_user.source] = [
                membership.structure for membership in service_user.memberships.all()
            ]

        if Auth.PRO_CONNECT not in {user.auth for user in self.service_users}:
            raise PermissionDenied("No ProConnect account detected accross the services")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activated_services"] = set(self.activated_services_with_memberships.keys())
        if {user.kind for user in self.service_users} == {NexusUserKind.GUIDE}:
            context["user_kind"] = NexusUserKind.GUIDE
        else:
            context["user_kind"] = NexusUserKind.FACILITY_MANAGER
        context["zendesk_form_url"] = ""  # FIXME: in a following commit
        context["logout_url"] = reverse("account_logout")  # FIXME: Redirect to nexus login page
        context["user_name"] = f"{self.request.user.first_name} {self.request.user.last_name[0]}"

        return context


class HomePageView(NexusMixin, TemplateView):
    template_name = "nexus/homepage.html"
    # Empty for now : it's just to test the layout seperately from all the views
