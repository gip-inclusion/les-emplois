import json

from django.http import HttpResponse

from itou.cities.models import City


def autocomplete(request):
    """
    Returns JSON compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """
    term = request.GET.get('term', '').strip()
    cities = []
    if term:
        cities = City.active_objects.filter(name__istartswith=term)
        cities = cities[:10]
        cities = [
            {
                "label": city.display_name,
                "value": city.display_name,
                "slug": city.slug,
            }
            for city in cities
        ]
    return HttpResponse(json.dumps(cities), 'application/json')
