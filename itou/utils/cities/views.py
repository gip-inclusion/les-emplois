import json

from django.conf import settings
from django.http import HttpResponse

from itou.utils.cities.models import City


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
            "label": str(city),
            "value": str(city),
            "slug": f"{city.slug}-{city.department}",
        }
        for city in cities
    ]
    return HttpResponse(json.dumps(cities), 'application/json')
