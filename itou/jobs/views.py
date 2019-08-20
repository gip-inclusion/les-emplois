import json

from django.db.models import Q
from django.http import HttpResponse

from itou.jobs.models import Appellation


def autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    terms = request.GET.get('term', '').strip().split()
    codes_to_exclude = request.GET.getlist('code', [])
    appellations = []

    if terms:

        q_query = Q()
        for term in terms:
            q_query &= Q(short_name__icontains=term) | Q(rome__code__icontains=term)

        appellations = Appellation.objects.filter(q_query).select_related('rome')

        if codes_to_exclude:
            appellations = appellations.exclude(code__in=codes_to_exclude)

        appellations = appellations[:10]

        appellations = [
            {
                "value": f"{appellation.short_name} ({appellation.rome.code})",
                "code": appellation.code,
                "rome": appellation.rome.code,
                "short_name": appellation.short_name,
            }
            for appellation in appellations
        ]

    return HttpResponse(json.dumps(appellations), 'application/json')
