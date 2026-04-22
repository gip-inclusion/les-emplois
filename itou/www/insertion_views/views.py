from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView
from django.views.generic.base import TemplateView

from itou.insertion.models import GenericReferenceItem, Service, Structure
from itou.insertion.opening_hours import format_osm_hours
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.urls import get_safe_url
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin


class StructureCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, TemplateView):
    template_name = "insertion/structure_card.html"

    def setup(self, request, structure_uid, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            Structure.objects.prefetch_related(
                Prefetch(
                    "services",
                    queryset=Service.objects.order_by("name").select_related("kind"),
                ),
            ),
            uid=structure_uid,
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "structure": self.structure,
            "matomo_custom_title": "Fiche structure d’insertion",
            "back_url": get_safe_url(self.request, "back_url", fallback_url=reverse("home:hp")),
        }


class ServiceDetailView(LoginRequiredMixin, DetailView):
    model = Service
    queryset = Service.objects.select_related(
        "source",
        "fee",
        "kind",
        "structure",
        "structure__source",
        "insee_city",
    ).prefetch_related(
        "thematics",
        "publics",
        Prefetch("receptions", queryset=GenericReferenceItem.objects.order_by("label")),
        "mobilizations",
        "mobilization_publics",
    )
    slug_field = "uid"
    slug_url_kwarg = "service_uid"
    template_name = "insertion/service_detail.html"
    context_object_name = "service"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formatted_opening_hours"] = format_osm_hours(self.object.opening_hours)
        context["back_url"] = "#"  # TODO: link to the service list once it exists
        context["matomo_custom_title"] = "Fiche de la service d'insértion"
        return context
