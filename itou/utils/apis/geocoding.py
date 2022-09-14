import logging

import httpx
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.utils.http import urlencode


logger = logging.getLogger(__name__)


class GeocodingDataException(Exception):
    pass


def call_ban_geocoding_api(address, post_code=None, limit=1):

    api_url = f"{settings.API_BAN_BASE_URL}/search/"

    args = {"q": address, "limit": limit}

    # `post_code` can be used to restrict the scope of the search.
    if post_code:
        args["postcode"] = post_code

    query_string = urlencode(args)
    url = f"{api_url}?{query_string}"

    try:
        r = httpx.get(url)
        r.raise_for_status()
    except httpx.HTTPError as e:
        logger.info("Error while requesting `%s`: %s", url, e)
        return None

    try:
        return r.json()["features"][0]
    except IndexError:
        logger.info("Geocoding error, no result found for `%s`", url)
        return None


def get_geocoding_data(address, post_code=None, limit=1):
    """
    Return a dict containing info about the given `address` or None if no result found.
    Contains parts of an address useful for objects like User
    but also some fields needed for ASP address formatting:
    - insee_code
    - number
    - lane
    - address (different from address_line_1)
    """

    data = call_ban_geocoding_api(address, post_code=post_code, limit=limit)

    if not data or not data.get("properties"):
        raise GeocodingDataException("Unable to get properties set for geocoding data")

    longitude = data["geometry"]["coordinates"][0]
    latitude = data["geometry"]["coordinates"][1]

    return {
        "score": data["properties"]["score"],
        "address_line_1": data["properties"]["name"],
        "number": data["properties"].get("housenumber", None),
        "lane": data["properties"].get("street", None),
        "address": data["properties"]["name"],
        "post_code": data["properties"]["postcode"],
        "insee_code": data["properties"]["citycode"],
        "city": data["properties"]["city"],
        "longitude": longitude,
        "latitude": latitude,
        "coords": GEOSGeometry(f"POINT({longitude} {latitude})"),
    }
