from django.shortcuts import get_object_or_404, render

from itou.siaes.models import Siae
from itou.utils.urls import get_safe_url


def card(request, siret, template_name="siaes/card.html"):
    """
    SIAE's card (or "Fiche" in French).
    """
    queryset = Siae.active_objects.prefetch_jobs_through(is_active=True)
    siae = get_object_or_404(queryset, siret=siret)
    next_url = get_safe_url(request, "next")
    context = {"next": next_url, "siae": siae}
    return render(request, template_name, context)
