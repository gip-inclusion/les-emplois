from django.db import models
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView
from django.views.generic.base import TemplateView

from itou.insertion import models as insertion_models
from itou.insertion.opening_hours import format_osm_hours
from itou.insertion.utils import get_orientation_jwt
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.pagination import pager
from itou.utils.readonly import ReadonlyViewMixin
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin


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
