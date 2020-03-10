import logging

import requests
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.utils.http import urlencode

logger = logging.getLogger(__name__)


def call_ban_geocoding_api(address, post_code=None, limit=1):

    api_url = f"{settings.API_BAN_BASE_URL}/search/"

    args = {"q": address, "limit": limit}

    # `post_code` can be used to restrict the scope of the search.
    if post_code:
        args["postcode"] = post_code

    query_string = urlencode(args)
    url = f"{api_url}?{query_string}"

    try:
        r = requests.get(url)
    except requests.exceptions.RequestException as e:
        logger.error("Error while fetching `%s`: %s", url, e)
        return None

    try:
        return r.json()["features"][0]
    except IndexError:
        logger.error("Geocoding error, no result found for `%s`", url)
        return None


def process_geocoding_data(data):

    if not data:
        return None

    longitude = data["geometry"]["coordinates"][0]
    latitude = data["geometry"]["coordinates"][1]

    return {
        "score": data["properties"]["score"],
        "address_line_1": data["properties"]["name"],
        "post_code": data["properties"]["postcode"],
        "city": data["properties"]["city"],
        "longitude": longitude,
        "latitude": latitude,
        "coords": GEOSGeometry(f"POINT({longitude} {latitude})"),
    }


def get_geocoding_data(address, post_code=None, limit=1):

    geocoding_data = call_ban_geocoding_api(address, post_code=post_code, limit=limit)

    return process_geocoding_data(geocoding_data)
