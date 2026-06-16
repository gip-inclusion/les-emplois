from data_inclusion.schema.v1.thematiques import Categorie
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import DetailView
from django.views.generic.base import TemplateView
from itoutils.django.decoupage_administratif.admin_division_parsing import get_division_label

from itou.insertion.models import GenericReferenceItem, Service, Structure
from itou.insertion.opening_hours import format_osm_hours
from itou.insertion.utils import get_orientation_jwt
from itou.users.perms import can_prefill_orientation_on_dora
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.readonly import ReadonlyViewMixin
from itou.utils.urls import get_safe_url


class StructureCardView(LoginNotRequiredMixin, ReadonlyViewMixin, TemplateView):
    template_name = "insertion/structure_card.html"

    def setup(self, request, structure_uid, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            Structure.objects.select_related("source").prefetch_related(
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


class ServiceDetailView(LoginNotRequiredMixin, DetailView):
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
        "mobilization_modes_beneficiaries",
        "mobilization_modes_professionals",
    )
    slug_field = "uid"
    slug_url_kwarg = "service_uid"
    template_name = "insertion/service_card.html"
    context_object_name = "service"

    def format_categories(self) -> list[tuple[str, str]]:
        formatted_categories = []
        for thematic in self.object.thematics.all():
            category = thematic.value.split("--")[0]
            category_label = Categorie(category).label
            subcategory_label = thematic.label
            formatted_categories.append((category_label, subcategory_label))
        return formatted_categories

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["formatted_opening_hours"] = format_osm_hours(self.object.opening_hours)
        context["back_url"] = get_safe_url(
            self.request,
            url=self.request.META.get("HTTP_REFERER"),
            fallback_url=reverse("home:hp"),
        )
        context["matomo_custom_title"] = "Fiche de la service d'insértion"
        context["orientation_jwt"] = (
            get_orientation_jwt(self.request) if can_prefill_orientation_on_dora(self.request) else None
        )
        context["geographic_perimeter"] = get_division_label(self.object.eligibility_zones) or "France entière"
        context["credential_documents"] = self.object.generate_credential_documents_info()
        context["show_mobilization_section"] = self.object.has_mobilization_modes()
        context["professionals_has_autre"] = any(
            m.value == "autre" for m in self.object.mobilization_modes_professionals.all()
        )
        context["beneficiaries_has_autre"] = any(
            m.value == "autre" for m in self.object.mobilization_modes_beneficiaries.all()
        )
        context["formatted_categories"] = self.format_categories()
        return context
