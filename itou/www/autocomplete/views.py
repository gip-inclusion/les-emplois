from django.contrib.postgres.search import TrigramSimilarity
from django.http import JsonResponse
from django.template.defaultfilters import slugify

from itou.asp.models import Commune
from itou.cities.models import City
from itou.jobs.models import Appellation
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
        cities = cities[:12]

        cities = [{"value": city.display_name, "slug": city.slug} for city in cities]

    return JsonResponse(cities, safe=False)


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

    return JsonResponse(appellations, safe=False)


def communes_autocomplete(request):
    """
    Autocomplete endpoint for INSEE communes (ASP ref. files)

    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get("term", "").strip()
    communes = []

    if term:
        communes = (
            Commune.objects.filter(end_date=None)
            .annotate(similarity=TrigramSimilarity("name", term))
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )
        communes = [
            {
                "value": f"{commune.name} ({commune.department_code})",
                "code": commune.code,
                "department": commune.department_code,
            }
            for commune in communes[:12]
        ]

    return JsonResponse(communes, safe=False)
