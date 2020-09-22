"""

Siae object logic used by the import_siae.py script is gathered here.

"""
from itou.siaes.management.commands._import_siae.liste_correspondants_techniques import EXTERNAL_ID_TO_AUTH_EMAIL
from itou.siaes.management.commands._import_siae.vue_af import (
    SIAE_KEY_TO_CONVENTION_END_DATE,
    VALID_SIAE_KEYS,
    get_siae_key,
)
from itou.siaes.models import Siae
from itou.utils.address.departments import department_from_postcode
from itou.utils.address.models import AddressMixin
from itou.utils.apis.geocoding import get_geocoding_data


def does_siae_have_a_valid_convention(siae):
    return get_siae_key(siae) in VALID_SIAE_KEYS


def should_siae_be_created(siae):
    return does_siae_have_a_valid_convention(siae) and siae.is_in_open_department


def could_siae_be_deleted(siae):
    return siae.members.count() == 0 and siae.job_applications_received.count() == 0


def get_siae_convention_end_date(siae):
    return SIAE_KEY_TO_CONVENTION_END_DATE.get(get_siae_key(siae))


def geocode_siae(siae):
    assert siae.address_on_one_line

    geocoding_data = get_geocoding_data(siae.address_on_one_line, post_code=siae.post_code)

    if geocoding_data:
        siae.geocoding_score = geocoding_data["score"]
        # If the score is greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable:
        # use data returned by the BAN API because it's better written using accents etc.
        # while the source data is in all caps etc.
        # Otherwise keep the old address (which is probably wrong or incomplete).
        if siae.geocoding_score >= AddressMixin.API_BAN_RELIABLE_MIN_SCORE:
            siae.address_line_1 = geocoding_data["address_line_1"]
        # City is always good due to `postcode` passed in query.
        # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
        siae.city = geocoding_data["city"]

        siae.coords = geocoding_data["coords"]

    return siae


def build_siae(row, kind):
    siae = Siae()
    siae.siret = row.siret
    siae.external_id = row.external_id
    siae.kind = kind
    siae.convention_end_date = get_siae_convention_end_date(siae)
    siae.naf = row.naf
    siae.source = Siae.SOURCE_ASP
    siae.name = row.name

    siae.phone = row.phone
    phone_is_valid = siae.phone and len(siae.phone) == 10
    if not phone_is_valid:
        siae.phone = ""  # siae.phone cannot be null in db

    siae.email = ""  # Do not make the authentification email public!
    siae.auth_email = EXTERNAL_ID_TO_AUTH_EMAIL.get(siae.external_id)

    street_num = row.street_num
    if street_num:
        street_num = int(street_num)
    street_num = f"{street_num or ''} {row.street_num_extra or ''}"
    street_name = f"{row.street_type or ''} {row.street_name or ''}"
    address_line_1 = f"{street_num} {street_name}"
    # Replace multiple spaces by a single space.
    address_line_1 = " ".join(address_line_1.split())
    siae.address_line_1 = address_line_1.strip()

    address_line_2 = f"{row.extra1 or ''} {row.extra2 or ''} {row.extra3 or ''}"
    # Replace multiple spaces by a single space.
    address_line_2 = " ".join(address_line_2.split())
    siae.address_line_2 = address_line_2.strip()

    # Avoid confusing case where line1 is empty and line2 is not.
    if not siae.address_line_1:
        siae.address_line_1 = siae.address_line_2
        siae.address_line_2 = ""

    siae.city = row.city
    siae.post_code = row.zipcode
    siae.department = department_from_postcode(siae.post_code)

    if should_siae_be_created(siae):
        siae = geocode_siae(siae)

    return siae
