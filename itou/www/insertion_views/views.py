import enum
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView
from django.views.generic.base import TemplateView

from itou.insertion import models as insertion_models
from itou.insertion.opening_hours import format_osm_hours
from itou.insertion.utils import get_orientation_jwt
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.pagination import pager
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.readonly import ReadonlyViewMixin
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin
from itou.www.utils.wizard import WizardView


logger = logging.getLogger(__name__)


class StructureCardView(LoginNotRequiredMixin, ReadonlyViewMixin, TemplateView):
    template_name = "insertion/structure_card.html"

    def setup(self, request, structure_uid, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            insertion_models.Structure.objects.select_related("source").prefetch_related(
                Prefetch(
                    "services",
                    queryset=insertion_models.Service.objects.order_by("name").select_related("kind"),
                ),
            ),
            uid=structure_uid,
        )

    def get_context_data(self, **kwargs):
        services_page = pager(self.structure.services.all(), self.request.GET.get("page"), items_per_page=5)

        return super().get_context_data(**kwargs) | {
            "structure": self.structure,
            "matomo_custom_title": "Fiche structure d’insertion",
            "back_url": get_safe_url(self.request, "back_url", fallback_url=reverse("home:hp")),
            "active_tab": "services" if self.request.GET.get("page") else "description",
            "services_page": services_page,
        }

    def get_template_names(self):
        if self.request.htmx:
            return ["insertion/includes/structure_card_tab_services.html"]
        return [self.template_name]


class ServiceCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, DetailView):
    model = insertion_models.Service
    queryset = insertion_models.Service.objects.select_related(
        "source",
        "fee",
        "kind",
        "structure",
        "structure__source",
        "insee_city",
    ).prefetch_related(
        "thematics",
        "publics",
        models.Prefetch("receptions", queryset=insertion_models.GenericReferenceItem.objects.order_by("label")),
        "mobilizations",
        "mobilization_publics",
    )
    slug_field = "uid"
    slug_url_kwarg = "service_uid"
    template_name = "insertion/service_card.html"
    context_object_name = "service"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formatted_opening_hours"] = format_osm_hours(self.object.opening_hours)
        context["back_url"] = "#"  # TODO: link to the service list once it exists
        context["matomo_custom_title"] = "Fiche de la service d'insértion"
        context["orientation_jwt"] = get_orientation_jwt(self.request)
        return context


class OrientationStep(enum.StrEnum):
    CONFORMITY = "valider-conformite"
    REFERENT = "completer-demande"
    DOCUMENTS = "documents-justificatifs"
    do_not_call_in_templates = enum.nonmember(True)


@login_required
def start_orientation(request, service_uid):
    service = get_object_or_404(insertion_models.Service, uid=service_uid, is_orientable_with_form=True)
    job_seeker = get_object_or_404(User, public_id=request.GET.get("job_seeker_public_id"), kind=UserKind.JOB_SEEKER)
    logger.info(
        "orientation wizard start user=%s service_uid=%s job_seeker=%s",
        request.user.pk,
        service.uid,
        job_seeker.public_id,
    )
    return OrientationWizardView.initialize_session_and_start(
        request,
        reset_url=reverse("insertion_views:service_card", kwargs={"service_uid": service.uid}),
        extra_session_data={
            "service_uid": service.uid,
            "job_seeker_public_id": str(job_seeker.public_id),
        },
    )


class OrientationWizardView(LoginRequiredMixin, WizardView):
    url_name = "insertion_views:orientation_steps"
    expected_session_kind = "orientation"
    template_name = "insertion/orientation_wizard.html"
    steps_config = {}

    def setup_wizard(self):
        self.service = get_object_or_404(
            insertion_models.Service.objects.select_related("kind", "structure"),
            uid=self.wizard_session.get("service_uid"),
        )
        self.job_seeker = get_object_or_404(
            User.objects.select_related("jobseeker_profile"),
            public_id=self.wizard_session.get("job_seeker_public_id"),
            kind=UserKind.JOB_SEEKER,
        )

    def done(self):
        return self.reset_url

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "service": self.service,
            "job_seeker": self.job_seeker,
            "can_view_personal_information": can_view_personal_information(self.request, self.job_seeker),
            "OrientationStep": OrientationStep,
        }
