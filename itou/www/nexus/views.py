import logging

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.views.generic import TemplateView

from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import NexusUser
from itou.nexus.utils import build_user, serialize_user


logger = logging.getLogger(__name__)


class NexusMixin:
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        # We cannot use UserPassesTestMixin because the call of serialize_user will crash
        # with a bad kind, and test_func is called later, in self.dispatch()
        if not (request.user.is_employer or request.user.is_prescriber):
            raise PermissionDenied("Votre type de compte ne permet pas d'afficher cette page.")

        self.service_users = list(NexusUser.objects.filter(email=self.request.user.email))
        user_data = serialize_user(request.user)
        self.service_users.append(build_user(user_data, Service.EMPLOIS))
        for activated_service in request.user.activated_services.all():
            self.service_users.append(build_user(user_data, activated_service.service))

        # Retrieve user data from nexus ressources
        self.activated_services = {user.source for user in self.service_users}

        if Auth.PRO_CONNECT not in {user.auth for user in self.service_users}:
            raise PermissionDenied("Seul un utilisateur ayant un compte ProConnect peut accéder à cette page.")

        if {user.kind for user in self.service_users if user.kind} == {NexusUserKind.GUIDE}:
            self.user_kind = NexusUserKind.GUIDE
        else:
            self.user_kind = NexusUserKind.FACILITY_MANAGER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activated_services"] = self.activated_services
        context["user_kind"] = self.user_kind
        context["zendesk_form_url"] = ""  # FIXME: in a following commit
        context["logout_url"] = reverse("account_logout")  # FIXME: Redirect to nexus login page
        context["user_name"] = f"{self.request.user.first_name} {self.request.user.last_name[0]}"
        context["emplois_badge_count"] = None
        if Service.EMPLOIS in self.activated_services:
            context["emplois_badge_count"] = 0  # FIXME Replace with active job desctiptions

        return context


class HomePageView(NexusMixin, TemplateView):
    template_name = "nexus/homepage.html"
    # Empty for now : it's just to test the layout separately from all the views
