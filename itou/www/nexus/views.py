import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from itoutils.urls import add_url_params

from itou.companies.models import Company, JobDescription
from itou.nexus.enums import Auth, NexusUserKind, Service
from itou.nexus.models import ActivatedService
from itou.nexus.utils import get_service_users
from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.users.enums import UserKind
from itou.utils.enums import ItouEnvironment
from itou.utils.templatetags.url_add_query import autologin_proconnect
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)

TALLY_URL = "https://tally.so/embed/Bza9Je?dynamicHeight=1"


# All class using this mixin will redirect unauthenticated users to nexus login page
@method_decorator(login_required(login_url=reverse_lazy("nexus:login")), name="dispatch")
class NexusMixin:
    menu = None

    # method_decorator requires the method to exist on the decorated class; define a passthrough.
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        # We cannot use UserPassesTestMixin because the call of serialize_user will crash
        # with a bad kind, and test_func is called later, in self.dispatch()
        if not request.user.is_caseworker:
            raise PermissionDenied("Votre type de compte ne permet pas d'afficher cette page.")

        service_users = get_service_users(user=request.user)

        # Retrieve user data from nexus ressources
        self.activated_services = {user.source for user in service_users}

        if Auth.PRO_CONNECT not in {user.auth for user in service_users}:
            raise PermissionDenied("Seul un utilisateur ayant un compte ProConnect peut accéder à cette page.")

        if {user.kind for user in service_users if user.kind} == {NexusUserKind.GUIDE}:
            self.user_kind = NexusUserKind.GUIDE
        else:
            self.user_kind = NexusUserKind.FACILITY_MANAGER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activated_services"] = self.activated_services
        context["user_kind"] = self.user_kind
        context["logout_url"] = add_url_params(reverse("account_logout"), {"redirect_url": reverse("nexus:login")})
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

        if settings.ITOU_ENVIRONMENT not in [ItouEnvironment.PROD, ItouEnvironment.TEST]:
            # mask outgoing prod links on non prod live instances
            context["dora_url"] = "https://staging.dora.inclusion.gouv.fr/"
            context["marche_url"] = "https://staging.lemarche.inclusion.beta.gouv.fr/"
            if Service.MON_RECAP in self.activated_services:
                context["monrecap_url"] = None  # Only keep the activation link

        context["menu"] = self.menu
        if self.menu in Service:
            context["service"] = self.menu

        return context


class HomePageView(NexusMixin, TemplateView):
    template_name = "nexus/homepage.html"
    menu = "homepage"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["all_services_activated"] = context["activated_services"] == set(Service.activable())
        context["new_service_shown"] = next(
            (service for service in Service.activable() if service not in context["activated_services"]), None
        )
        context["a_b_test_url"] = get_absolute_url(reverse("nexus:homepage")).replace("/", "\\/")
        context["departments_list"] = ", ".join(settings.NEXUS_MVP_DEPARTMENTS)
        return context


@require_POST
def activate_mon_recap(request):
    next_url = reverse("nexus:mon_recap")
    ActivatedService.objects.activate(user=request.user, service=Service.MON_RECAP)
    messages.success(
        request, f"Service activé||Vous avez bien activé le service {Service.MON_RECAP.label}", extra_tags="toast"
    )
    return HttpResponseRedirect(next_url)


class DoraView(NexusMixin, TemplateView):
    template_name = "nexus/dora.html"
    menu = Service.DORA


class EmploisView(NexusMixin, TemplateView):
    menu = Service.EMPLOIS

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if self.user_kind != NexusUserKind.FACILITY_MANAGER:
            raise PermissionDenied("Votre type de compte ne permet pas d'afficher cette page.")
        self.has_company_memberships = any(isinstance(org, Company) for org in self.request.organizations)

    def get_template_names(self):
        if Service.EMPLOIS not in self.activated_services:
            return ["nexus/emplois_inactive.html"]
        if self.has_company_memberships:
            return ["nexus/emplois_job_descriptions.html"]
        return ["nexus/emplois_no_companies.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if Service.EMPLOIS in self.activated_services and self.has_company_memberships:
            # TODO(alaurent) We can have facility managers that are prescribers on les emplois
            # We should handle it correctly someday
            context["job_descriptions"] = JobDescription.objects.filter(
                is_active=True, company=self.request.current_organization
            )
            context["job_description_count"] = len(context["job_descriptions"])
        return context


class MarcheView(NexusMixin, TemplateView):
    template_name = "nexus/marche.html"
    menu = Service.MARCHE


class MonRecapView(NexusMixin, TemplateView):
    template_name = "nexus/mon_recap.html"
    menu = Service.MON_RECAP


class PilotageView(NexusMixin, TemplateView):
    template_name = "nexus/pilotage.html"
    menu = Service.PILOTAGE


class StructuresView(NexusMixin, TemplateView):
    template_name = "nexus/structures.html"
    menu = "structures"


class ContactView(NexusMixin, TemplateView):
    template_name = "nexus/contact.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tally_url"] = TALLY_URL
        return context


@login_not_required
def login(request, template_name="nexus/login.html"):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("nexus:homepage"))

    params = {
        # we don't care which kind is chosen since we only allow login and both kinds are commutable
        "user_kind": UserKind.PRESCRIBER,
        "previous_url": request.get_full_path(),
        "channel": ProConnectChannel.NEXUS,
        "next_url": reverse("nexus:homepage"),
    }
    pro_connect_url = reverse("pro_connect:authorize", query=params) if settings.PRO_CONNECT_BASE_URL else None
    return render(
        request,
        template_name,
        context={
            "pro_connect_url": pro_connect_url,
            "matomo_account_type": "non défini",
            "tally_url": TALLY_URL,
        },
    )
