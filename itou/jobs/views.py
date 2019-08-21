import json

from django.http import HttpResponse

from itou.jobs.models import Appellation


def autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get('term', '').strip()
    appellations = []

    if term:
        codes_to_exclude = request.GET.getlist('code', [])
        appellations = [
            {
                "value": f"{appellation.name} ({appellation.rome.code})",
                "code": appellation.code,
                "rome": appellation.rome.code,
                "name": appellation.name,
            }
            for appellation in Appellation.objects.autocomplete(term, codes_to_exclude, limit=10)
        ]

    return HttpResponse(json.dumps(appellations), 'application/json')
