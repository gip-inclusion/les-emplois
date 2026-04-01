from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.views.generic import DetailView

from itou.dora.models import ReferenceDatum, Service


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
        models.Prefetch("receptions", queryset=ReferenceDatum.objects.order_by("label")),
        "mobilizations",
        "mobilization_publics",
    )
    slug_field = "uid"
    slug_url_kwarg = "uid"
    template_name = "services/detail.html"
    context_object_name = "service"
