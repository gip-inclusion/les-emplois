import json

from django.conf import settings
from django.http import HttpResponse

from itou.cities.models import City


def autocomplete(request, template_name='siae/details.html'):
    """
    Returns JSON data for the city autocomplete form field.
    """
    term = request.GET.get('term')
    cities = City.objects.filter(department__in=settings.ITOU_TEST_DEPARTMENTS)
    if term:
        cities = cities.filter(name__istartswith=term)
    cities = cities[:10]
    cities = [
        {
            "label": f"{city.name} ({city.department})",
            "value": f"{city.name} ({city.department})",
            "slug": f"{city.slug}-{city.department}" if city.department else {city.slug},
        }
        for city in cities
    ]
    return HttpResponse(json.dumps(cities), 'application/json')
