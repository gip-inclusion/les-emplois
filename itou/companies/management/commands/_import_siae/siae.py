"""

SIAE object logic used by the import_siae.py script is gathered here.

All these helpers are specific to SIAE logic (not GEIQ, EA, EATT).

"""

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.management.commands._import_siae.utils import geocode_siae
from itou.companies.management.commands._import_siae.vue_af import ACTIVE_SIAE_KEYS
from itou.companies.management.commands._import_siae.vue_structure import SIRET_TO_ASP_ID
from itou.companies.models import Company


def does_siae_have_an_active_convention(siae):
    asp_id = SIRET_TO_ASP_ID.get(siae.siret)
    siae_key = (asp_id, siae.kind)
    return siae_key in ACTIVE_SIAE_KEYS


def should_siae_be_created(siae):
    return does_siae_have_an_active_convention(siae)


def build_siae(row, kind):
    """
    Build a siae object from a dataframe row.

    Only for SIAE, not for GEIQ nor EA nor EATT.
    """
    siae = Company()
    siae.siret = row.siret
    siae.kind = kind
    siae.naf = row.naf
    siae.source = Company.SOURCE_ASP
    siae.name = row["name"]  # row.name surprisingly returns the row index.
    assert not siae.name.isnumeric()

    siae.phone = row.phone
    phone_is_valid = siae.phone and len(siae.phone) == 10
    if not phone_is_valid:
        siae.phone = ""  # siae.phone cannot be null in db

    siae.email = ""  # Do not make the authentification email public!
    siae.auth_email = row.auth_email

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
    siae.post_code = row.post_code
    siae.department = department_from_postcode(siae.post_code)

    if should_siae_be_created(siae):
        siae = geocode_siae(siae)

    return siae
