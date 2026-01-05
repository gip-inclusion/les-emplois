import logging

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.views.generic import TemplateView

from itou.companies.models import JobDescription
from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import ActivatedService, NexusUser
from itou.nexus.utils import build_user, serialize_user
from itou.utils.enums import ItouEnvironment
from itou.utils.templatetags.url_add_query import autologin_proconnect
from itou.utils.urls import get_absolute_url


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
        if Service.EMPLOIS in self.activated_services and self.user_kind == NexusUserKind.FACILITY_MANAGER:
            # No job descriptions for prescribers : The user may have a facility manager role in another service
            if self.request.user.is_employer:
                context["emplois_badge_count"] = JobDescription.objects.filter(
                    is_active=True, company_id__in=[company.pk for company in self.request.organizations]
                ).count()

        # It's always activated
        context["emplois_url"] = reverse("dashboard:index")

        # It's the same in both cases
        context["dora_url"] = autologin_proconnect("https://dora.inclusion.gouv.fr/", self.request.user)

        if Service.MARCHE in self.activated_services:
            context["marche_url"] = "https://lemarche.inclusion.gouv.fr/accounts/login/"
        else:
            context["marche_url"] = "https://lemarche.inclusion.gouv.fr/accounts/signup/"

        if Service.MON_RECAP in self.activated_services:
            context["monrecap_url"] = "https://mon-recap.inclusion.beta.gouv.fr/formulaire-commande-carnets/"
        else:
            context["monrecap_url"] = reverse("nexus:activate_mon_recap")

        context["pilotage_url"] = reverse("dashboard:index_stats")

        if Service.COMMUNAUTE in self.activated_services:
            context["communaute_url"] = autologin_proconnect(
                "https://communaute.inclusion.gouv.fr/topics/", self.request.user
            )
        else:
            context["communaute_url"] = autologin_proconnect("https://communaute.inclusion.gouv.fr", self.request.user)

        if settings.ITOU_ENVIRONMENT not in [ItouEnvironment.PROD, ItouEnvironment.TEST]:
            # mask outgoing prod links on non prod live instances
            context["dora_url"] = "https://staging.dora.inclusion.gouv.fr/"
            context["marche_url"] = "https://staging.lemarche.inclusion.beta.gouv.fr/"
            if Service.MON_RECAP in self.activated_services:
                context["monrecap_url"] = None  # Only keep the activation link
            context["communaute_url"] = None  # No demo available

        if hasattr(self, "service"):
            context["service"] = self.service

        return context


class HomePageView(NexusMixin, TemplateView):
    template_name = "nexus/homepage.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_services_activated"] = context["activated_services"] == set(Service.activable())
        context["new_service_shown"] = next(
            (service for service in Service.activable() if service not in context["activated_services"]), None
        )
        context["a_b_test_url"] = get_absolute_url(reverse("nexus:homepage")).replace("/", "\\/")
        return context


def activate_mon_recap(request):
    if request.method != "POST":
        raise Http404

    next_url = reverse("nexus:mon_recap")
    try:
        ActivatedService.objects.create(user=request.user, service=Service.MON_RECAP)
    except Exception:
        logger.exception("Service already activated")
    messages.success(
        request, f"Service activé||Vous avez bien activé le service {Service.MON_RECAP.label}", extra_tags="toast"
    )

    return HttpResponseRedirect(next_url)


class CommunauteView(NexusMixin, TemplateView):
    template_name = "nexus/communaute.html"
    service = Service.COMMUNAUTE


class DoraView(NexusMixin, TemplateView):
    template_name = "nexus/dora.html"
    service = Service.DORA


class EmploisView(NexusMixin, TemplateView):
    service = Service.EMPLOIS

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.user_kind != NexusUserKind.FACILITY_MANAGER:
            # The user doesn't have access to this page
            return Http404

    def get_template_names(self):
        return [
            "nexus/emplois_structure.html"
            if Service.EMPLOIS in self.activated_services
            else "nexus/emplois_inactive.html"
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if Service.EMPLOIS in self.activated_services:
            # TODO(alaurent) We can have facility managers that are prescribers on les emplois
            # We should handle it correctly someday
            context["job_descriptions"] = JobDescription.objects.filter(
                is_active=True, company=self.request.current_organization
            )
            context["job_description_count"] = len(context["job_descriptions"])
        return context


class MarcheView(NexusMixin, TemplateView):
    template_name = "nexus/marche.html"
    service = Service.MARCHE


class MonRecapView(NexusMixin, TemplateView):
    template_name = "nexus/mon_recap.html"
    service = Service.MON_RECAP


class PilotageView(NexusMixin, TemplateView):
    template_name = "nexus/pilotage.html"
    service = Service.PILOTAGE
