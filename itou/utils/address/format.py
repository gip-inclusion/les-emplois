from unidecode import unidecode

from itou.asp.models import LaneExtension, LaneType, find_lane_type_aliases
from itou.users.models import User
from itou.utils.apis.geocoding import get_geocoding_data


def format_address(obj, update_coords=False):
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
    - city: name of city
    - post_code: postal code
    - insee_code: INSEE code of the city (Itou)

    INSEE code can be checked against ASP ref for further validation.

    Returns a (result,error) tuple:
    - OK => (result_dict, None),
    - KO => (None, error_message)
    """
    if not isinstance(obj, User):
        return None, "Only valid for User objects"

    # Do we have enough data to make an extraction?
    if not obj.post_code or not obj.address_line_1:
        return None, "Incomplete address data"

    # first we use geo API to get a 'lane' and a number
    address = get_geocoding_data(obj.address_line_1, post_code=obj.post_code)

    if not address:
        return None, "Geocoding error, unable to get result"

    result = {}

    # Street extension processing (bis, ter ...)
    # Extension is part of the resulting streetnumber geo API field
    number_plus_ext = address.get("number")
    if number_plus_ext:
        number, *extension = number_plus_ext.split()

        if number:
            result["number"] = number

        if extension:
            extension = extension[0]
            ext = LaneExtension.with_similar_name_or_value(extension)
            if ext:
                result["std_extension"] = ext.name
            else:
                result["non_std_extension"] = extension

    lane = None
    if not address.get("lane") and not address.get("address"):
        print(address)
        return None, "Unable to get address lane"
    else:
        lane = address.get("lane") or address.get("address")
        lane = unidecode(lane)
        result["lane"] = lane

    # Lane type processing (Avenue, RUe, Boulevard ...)
    lane_type = lane.split(maxsplit=1)[0]

    lt = (
        # The API field is similar to know lane type,
        # example: got "Av" for name "AV" (Avenue)
        LaneType.with_similar_name(lane_type)
        # The API field is similar to an exiting value
        # example: got "allee" for "Allée"
        or LaneType.with_similar_value(lane_type, fmt=lambda x: unidecode(x.lower()))
        # Maybe the geo API mispelled the lane type (happens sometimes)
        # so we use an aliases table as a last change to get the type
        # example: got "R" or "r" instead of "Rue"
        or find_lane_type_aliases(lane)
    )

    if lt:
        result["lane_type"] = lt.name
    else:
        return None, f"Can't find lane type: {lane_type}"

    # INSEE code: must double check with ASP ref file
    result["insee_code"] = address.get("insee_code")
    result["post_code"] = address.get("post_code")
    result["city"] = address.get("city")

    if update_coords and address.get("coords", None) and address.get("score", -1) > obj.get("geocoding_score", 0):
        # User, Siae and PrescribersOrganisation all have score and coords
        # If update_coords is True AND if we get a better geo score,
        # the existing address will be updated
        obj.coords = address["coords"]
        obj.geocoding_score = address["score"]
        obj.save()

    return result, None
