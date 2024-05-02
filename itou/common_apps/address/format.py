import re

from unidecode import unidecode

from itou.asp.models import LaneExtension, LaneType, find_lane_type_aliases
from itou.cities.models import City
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.apis.geocoding import get_geocoding_data


ERROR_HEXA_CONVERSION = "Impossible de transformer cet objet en adresse HEXA"
ERROR_GEOCODING_API = "Erreur de geocoding, impossible d'obtenir un résultat"
ERROR_INCOMPLETE_ADDRESS_DATA = "Données d'adresse incomplètes"
ERROR_UNKNOWN_ADDRESS_LANE = "Impossible d'obtenir le nom de la voie"

LANE_NUMBER_RE = r"^([0-9]{1,5})(.*?)$"
ADDITIONAL_ADDRESS_RE = r"^[a-zA-Z0-9@ ]{,32}$"


def format_address(obj):
    """
    Formats the address contained in obj into a valid address "structure" for ASP ER exports.

    Heavily relies on geo.api.gouv.fr API to do parts of the job for us:
    - extracting lane number and extension
    - giving a geocoding score / threshold in order to improve an existing DB address
    - validation of a real-world address

    Employee records ("Fiches salarié") contains 2 addresses of this kind.

    See validation of ASP address for expected/valid fields.

    Output fields:
    - number (opt.): number in the lane
    - std_extension (opt.): One of the ASP ref lane extension (see LaneExtension)
    - non_std_extension (opt.): if another extension is detected
    - lane: name of the lane
    - lane_type: One of the ASP ref lane type (see LaneType)
    - additional_address : further details on the address (if available)
    - city: name of city
    - post_code: postal code
    - insee_code: INSEE code of the city (Itou)

    INSEE code can be checked against ASP ref for further validation.

    Returns a (result,error) tuple:
    - OK => (result_dict, None),
    - KO => (None, error_message)
    """
    if not obj:
        return None, ERROR_HEXA_CONVERSION

    # Do we have enough data to make an extraction?
    if not obj.geocoding_address:
        return None, ERROR_INCOMPLETE_ADDRESS_DATA

    try:
        # first we use geo API to get a 'lane' and a number
        address = get_geocoding_data(obj.geocoding_address, post_code=obj.post_code)
    except GeocodingDataError as ex:
        return None, ERROR_GEOCODING_API + f" : {str(ex)}"

    # Default values
    additional_address = unidecode(obj.address_line_2)
    result = {
        "number": "",
        "non_std_extension": "",
        "additional_address": additional_address if re.match(ADDITIONAL_ADDRESS_RE, additional_address) else "",
    }

    # Street extension processing (bis, ter ...)
    # Extension is part of the resulting streetnumber geo API field
    number_plus_ext = address.get("number")

    if number_plus_ext:
        # API change : now extension can be "stuck" to lane number
        # This was not he case before (space in between)
        # REGEX to the rescue to fix ASP error 3323
        [[number, extension]] = re.findall(LANE_NUMBER_RE, number_plus_ext)

        if number:
            result["number"] = number

        if extension:
            extension = extension[0]
            ext = LaneExtension.with_similar_name_or_value(extension)
            if ext:
                result["std_extension"] = ext.name or ""
            else:
                result["non_std_extension"] = extension.upper()

    lane = None
    if not address.get("lane") and not address.get("address"):
        return None, ERROR_UNKNOWN_ADDRESS_LANE

    lane = address.get("lane") or address.get("address")
    lane = unidecode(lane)
    result["lane"] = lane

    # Lane type processing (Avenue, RUe, Boulevard ...)
    lane_type, *rest = lane.split(maxsplit=1)

    lt = (
        # The API field is similar to know lane type,
        # example: got "Av" for name "AV" (Avenue)
        LaneType.with_similar_name(lane_type)
        # The API field is similar to an exiting value
        # example: got "allee" for "Allée"
        or LaneType.with_similar_value(lane_type)
        # Maybe the geo API mispelled the lane type (happens sometimes)
        # so we use an aliases table as a last change to get the type
        # example: got "R" or "r" instead of "Rue"
        or find_lane_type_aliases(lane)
        # If all previous options have failed, fallback to "lieu-dit" as lane type.
        # This will fix some geolocation errors, f.i. when
        # lane types are not in french and not referenced by ASP.
        # (in Brittany or Basque country ...)
        or LaneType.LD
    )

    result["lane_type"] = lt.name
    # If split is successful, then we can strip the lane type
    # from the lane name for a better result
    result["lane"] = rest[0] if rest else lane_type

    # INSEE code: must double check with ASP ref file
    result["insee_code"] = address.get("insee_code")
    result["city"] = address.get("city")

    postal_code = address.get("post_code")
    if not postal_code and result["insee_code"]:
        # Don't try to do smart things when there is multiple post codes, taking the first one should be enough.
        postal_code = City.objects.get(code_insee=result["insee_code"]).post_codes[0]
    result["post_code"] = postal_code

    return result, None
