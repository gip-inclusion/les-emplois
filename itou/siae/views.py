from django.shortcuts import render

from itou.cities.models import City
from itou.siae.forms import SiaeSearchForm
from itou.siae.models import Siae
from itou.utils.pagination import pager


def search(request, template_name='siae/search_results.html'):

    form = SiaeSearchForm(data=request.GET)
    siaes_page = None

    if form.is_valid():
        city = form.cleaned_data['city']
        distance_km = form.cleaned_data['distance']
        siaes = Siae.active_objects.within(city.coords, distance_km)
        siaes_page = pager(siaes, request.GET.get('page'), items_per_page=10)

    context = {
        'form': form,
        'siaes_page': siaes_page,
    }
    return render(request, template_name, context)


def card(request, template_name='siae/card.html'):
    context = {}
    return render(request, template_name, context)
