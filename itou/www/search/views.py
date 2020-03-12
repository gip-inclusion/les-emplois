from django.shortcuts import render

from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.search.forms import SiaeSearchForm


def search_siaes(request, template_name="search/siaes_search_results.html"):

    form = SiaeSearchForm(data=request.GET)
    siaes_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]
        kind = form.cleaned_data["kind"]

        siaes = (
            Siae.active_objects.within(city.coords, distance_km)
            .prefetch_job_description_through(is_active=True)
            .prefetch_related("members")
        )
        if kind:
            siaes = siaes.filter(kind=kind)
        siaes_page = pager(siaes, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "siaes_page": siaes_page}
    return render(request, template_name, context)
