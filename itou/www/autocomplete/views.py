from datetime import datetime
from os.path import commonprefix

from django.db.models import Q
from django.http import JsonResponse
from unidecode import unidecode

from itou.asp.models import Commune
from itou.cities.models import City
from itou.jobs.models import Appellation
from itou.siaes.models import SiaeJobDescription


# Consider that after 50 matches the user should refine its search.
MAX_CITIES_TO_RETURN = 50


def sanitize(string):
    return unidecode(string.lower())


def cities_autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get("term", "").strip()
    cities = []

    if term:
        if term.isdigit():
            cities = City.objects.filter(post_codes__contains=[term]).order_by("name", "department")[
                :MAX_CITIES_TO_RETURN
            ]

        else:
            term = unidecode(term.lower())
            term_spaced = term.replace("-", " ")
            term_hyphenated = term.replace(" ", "-")
            index_term = commonprefix([term_spaced, term_hyphenated])
            cities = sorted(
                # The double search does not seem ideal, but we *did* start with a trigram similarity
                # and word similarity approach. It is disappointing since it does return results that
                # are not expected, for instance results containing letters not present in the search.
                # It has been decided with the UX to use the simplest approach. Secondly, it seems
                # that most people look for a city by "the start of the name", not by "any word within
                # the name" so the icontains lookup, ordered by index of the matching string, feels more
                # natural.
                # The hyphenated/unhyphenated thing has been added considering the mess that hyphens
                # represent in french city names. It is ugly, but simpler than the other approach which
                # could have been to look for the slugs, but requires a perfect sync of th slug and name
                # at all times, just for the search.
                City.objects.filter(
                    Q(name__unaccent__icontains=term_spaced) | Q(name__unaccent__icontains=term_hyphenated)
                )[:MAX_CITIES_TO_RETURN],
                # - the results __starting__ by the searched term are favoured (Paris over Cormeil-en-Parisis)
                # - then if the length is the same, by alphabetic order
                # - then if everything is the same (Sainte-Colombe...) by department.
                key=lambda c: (unidecode(c.name.lower()).index(index_term), c.name, c.department),
            )

        cities = [{"value": city.display_name, "slug": city.slug} for city in cities]

    return JsonResponse(cities, safe=False)


def jobs_autocomplete(request):
    """
    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """

    term = request.GET.get("term", "").strip()
    siae_id = request.GET.get("siae_id", "").strip()
    appellations = []

    # Fetch excluded codes:
    # SIAE already have job descriptions with these codes.
    excluded_codes = (
        SiaeJobDescription.objects.filter(siae__id=siae_id)
        .select_related("appellation", "siae")
        .values_list("appellation__code", flat=True)
    )

    if term:
        appellations = [
            {
                "value": f"{appellation.name} ({appellation.rome.code})",
                "code": appellation.code,
                "rome": appellation.rome.code,
                "name": appellation.name,
            }
            for appellation in Appellation.objects.autocomplete(term, codes_to_exclude=excluded_codes, limit=10)
        ]

    return JsonResponse(appellations, safe=False)


def communes_autocomplete(request):
    """
    Autocomplete endpoint for INSEE communes (ASP ref. files)

    Slight variation : a `date` parameter is sent with search term
    in order to get valid INSEE codes (with this date within a period between
    commune.start_date and commune.end_date)

    Returns JSON data compliant with the jQuery UI Autocomplete Widget:
    https://api.jqueryui.com/autocomplete/#option-source
    """
    communes = []
    term = request.GET.get("term", "").strip()

    try:
        dt = datetime.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        # Can't extract date in ISO format: use today as fallback
        dt = datetime.now()

    active_communes_qs = Commune.objects.filter(start_date__lte=dt).filter(Q(end_date=None) | Q(end_date__gt=dt))
    if term:
        if term.isdigit():
            communes = active_communes_qs.filter(code__startswith=term).order_by("name", "code")[:10]
        else:
            communes = sorted(
                active_communes_qs.filter(name__unaccent__icontains=term),
                # - the results starting by the searched term are favoured (Paris over Cormeil-en-Parisis)
                # - then if the length is the same, by alphabetic order
                # - then if everything is the same (Sainte-Colombe...) by department.
                key=lambda c: (sanitize(c.name).index(sanitize(term)), c.name, c.department_code),
            )

        communes = [
            {
                "value": f"{commune.name} ({commune.department_code})",
                "code": commune.code,
                "department": commune.department_code,
            }
            for commune in communes[:10]
        ]

    return JsonResponse(communes, safe=False)
