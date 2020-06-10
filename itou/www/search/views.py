from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.search.forms import PrescriberSearchForm, SiaeSearchForm


def search_siaes(request, template_name="search/siaes_search_results.html"):

    form = SiaeSearchForm(data=request.GET or None)
    siaes_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]
        kind = form.cleaned_data["kind"]

        siaes = (
            Siae.objects.within(city.coords, distance_km)
            .shuffle()
            .annotate(num_active_members=Count("members", filter=Q(members__is_active=True)))
            .prefetch_job_description_through(is_active=True)
            .prefetch_related("members")
        )
        if kind:
            siaes = siaes.filter(kind=kind)
        siaes_page = pager(siaes, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "siaes_page": siaes_page}
    return render(request, template_name, context)


@login_required
def search_prescribers(request, template_name="search/prescribers_search_results.html"):

    form = PrescriberSearchForm(data=request.GET or None)
    prescriber_orgs_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]

        prescriber_orgs = PrescriberOrganization.objects.filter(is_authorized=True).within(city.coords, distance_km)
        prescriber_orgs_page = pager(prescriber_orgs, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "prescriber_orgs_page": prescriber_orgs_page}
    return render(request, template_name, context)
