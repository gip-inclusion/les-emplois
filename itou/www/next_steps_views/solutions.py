"""« Trouver une solution »: the insertion services that work on a barrier, around the job seeker.

The side drawer lists what the services search finds for the barrier's category and the job seeker's city, with the
same rules (Service.objects.search); a service opens in the drawer too, and so does the orientation towards it
(journeys.OrientationJourney). The full search stays one link away, for its other filters.
"""

from data_inclusion.schema import v1 as data_inclusion_v1
from django.urls import reverse

from itou.cities.models import City
from itou.insertion.models import Service
from itou.www.next_steps_views.barriers import SEARCH_CATEGORIES


# How the services receive people: the search's own values, with the drawer's labels.
RECEPTIONS = {
    "": "Tous",
    data_inclusion_v1.ModeAccueil.EN_PRESENTIEL.value: "En présentiel",
    data_inclusion_v1.ModeAccueil.A_DISTANCE.value: "À distance",
}


def job_seeker_city(job_seeker):
    """The city the search starts from, as the search page pre-fills it: the job seeker's."""
    if not job_seeker.city_slug:
        return None
    return City.objects.filter(slug=job_seeker.city_slug).first()


def search_services(city, key, reception=""):
    category = SEARCH_CATEGORIES[key]
    thematics = [thematic.value for thematic in data_inclusion_v1.Thematique if thematic.value.startswith(category)]
    services = Service.objects.search(city=city, thematics=thematics, reception=reception, service_types=[])
    return services.select_related("structure", "source")


def solutions_url(job_seeker, key, **query):
    return reverse(
        "next_steps_views:solutions",
        kwargs={"public_id": job_seeker.public_id, "barrier": key.lower()},
        query={name: value for name, value in query.items() if value} or None,
    )


def service_url(job_seeker, service, key=None):
    """A service in the side drawer; from a barrier's solutions, it leads back to them."""
    return reverse(
        "next_steps_views:service",
        kwargs={"public_id": job_seeker.public_id, "service_id": service.pk},
        query={"frein": key.lower()} if key else None,
    )
