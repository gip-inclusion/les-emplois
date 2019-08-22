import json

from django.contrib.postgres.search import TrigramSimilarity
from django.http import HttpResponse
from django.template.defaultfilters import slugify

from itou.cities.models import City
from itou.utils.swear_words import get_city_swear_words_slugs


def autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get('term', '').strip()
    cities = []

    if term and slugify(term) not in get_city_swear_words_slugs():

        cities = (
            City.active_objects
            .annotate(similarity=TrigramSimilarity('name', term))
            .filter(similarity__gt=0.1)
            .order_by('-similarity')
        )
        cities = cities[:10]

        cities = [
            {
                "value": city.display_name,
                "slug": city.slug,
            }
            for city in cities
        ]

    return HttpResponse(json.dumps(cities), 'application/json')
