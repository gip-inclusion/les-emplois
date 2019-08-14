from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils.http import is_safe_url

from itou.cities.models import City
from itou.siaes.forms import SiaeSearchForm
from itou.siaes.models import Siae
from itou.utils.pagination import pager


def search(request, template_name='siae/search_results.html'):

    form = SiaeSearchForm(data=request.GET)
    siaes_page = None

    if form.is_valid():
        city = form.cleaned_data['city']
        distance_km = form.cleaned_data['distance']
        siaes = Siae.active_objects.within(city.coords, distance_km).prefetch_related('job_appellations')
        siaes_page = pager(siaes, request.GET.get('page'), items_per_page=10)

    context = {
        'form': form,
        'siaes_page': siaes_page,
    }
    return render(request, template_name, context)


def card(request, siret, template_name='siae/card.html'):
    """
    SIAE's card, or "Fiche" in French.
    """
    siae = get_object_or_404(Siae.active_objects, siret=siret)

    next_url = request.GET.get('next')
    url_is_safe = is_safe_url(url=next_url, allowed_hosts=settings.ALLOWED_HOSTS, require_https=request.is_secure())

    context = {
        'next': next_url if url_is_safe else None,
        'siae': siae,
    }
    return render(request, template_name, context)
