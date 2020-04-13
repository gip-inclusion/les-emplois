import json

from django.contrib.postgres.search import TrigramSimilarity
from django.http import HttpResponse
from django.template.defaultfilters import slugify

from itou.cities.models import City
from itou.jobs.models import Appellation
from itou.prescribers.models import PrescriberOrganization
from itou.utils.swear_words import get_city_swear_words_slugs


def cities_autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get("term", "").strip()
    cities = []

    if term and slugify(term) not in get_city_swear_words_slugs():
        cities = (
            City.objects.annotate(similarity=TrigramSimilarity("name", term))
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )
        cities = cities[:10]

        cities = [{"value": city.display_name, "slug": city.slug} for city in cities]

    return HttpResponse(json.dumps(cities), "application/json")


def jobs_autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get("term", "").strip()
    appellations = []

    if term:
        codes_to_exclude = request.GET.getlist("code", [])
        appellations = [
            {
                "value": f"{appellation.name} ({appellation.rome.code})",
                "code": appellation.code,
                "rome": appellation.rome.code,
                "name": appellation.name,
            }
            for appellation in Appellation.objects.autocomplete(term, codes_to_exclude, limit=10)
        ]

    return HttpResponse(json.dumps(appellations), "application/json")


def prescriber_authorized_organizations_autocomplete(request):
    term = request.GET.get("term", "").strip()

    organizations = (
        [
            {"value": org.name, "id": org.id}
            for org in PrescriberOrganization.objects.autocomplete(term)
            if org.is_authorized and org.kind != PrescriberOrganization.Kind.PE
        ]
        if term
        else []
    )

    return HttpResponse(json.dumps(organizations), "application/json")
