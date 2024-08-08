from urllib.parse import quote, urlencode

from itou.utils.constants import IMMERSION_FACILE_SITE_URL


def immersion_search_url(user):
    """
    :return: a search URL on Immersion Facilitée's site for parameterized user
    """
    params = {"mtm_campaign": "les-emplois-recherche-immersion", "mtm_kwd": "les-emplois-recherche-immersion"}

    # in testing, there are some differences between how addresses are validated between
    # IF's service and ours, so only we can only consider the geolocation reliable if
    # lat/lng is present
    if user.coords:
        params["distanceKm"] = 20
        params["latitude"] = user.latitude
        params["longitude"] = user.longitude
        params["sortedBy"] = "distance"

        if user.insee_city:
            address_parts = [user.insee_city.name, user.insee_city.region, "France"]
        else:
            address_parts = [user.city, user.region, "France"]

        if all(address_parts):
            params["place"] = ", ".join(address_parts)

    return f"{IMMERSION_FACILE_SITE_URL}/recherche?{urlencode(params, quote_via=quote)}"
