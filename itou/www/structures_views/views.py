from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.views.generic.base import TemplateView

from itou.dora.models import Service, Structure
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.pagination import pager
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin


class StructureCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, TemplateView):
    template_name = "structures/card.html"

    def setup(self, request, structure_pk, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.structure = get_object_or_404(
            Structure.objects.prefetch_related(
                Prefetch(
                    "service_set",
                    queryset=Service.objects.order_by("name").select_related("kind"),
                ),
            ),
            pk=structure_pk,
        )

    def get_context_data(self, **kwargs):
        services_page = pager(self.structure.service_set.all(), self.request.GET.get("page"), items_per_page=5)

        return super().get_context_data(**kwargs) | {
            "structure": self.structure,
            "active_tab": "services" if self.request.GET.get("page") else "description",
            "services_page": services_page,
        }

    def get_template_names(self):
        if self.request.htmx:
            return ["structures/includes/structure_card_tab_services.html"]
        return [self.template_name]
