import logging
from typing import NamedTuple

import pandas as pd
from django.core.cache import cache

from itou.gps.models import FranceTravailContact
from itou.utils.python import timeit


logger = logging.getLogger(__name__)


class FranceTravailContactDetails(NamedTuple):
    prescriber_name: str
    prescriber_email: str


GPS_ADVISORS_KEY = "GPS_ADVISORS"


@timeit
def parse_gps_advisors_file(import_file):
    # NOM | PRENOM | NIR | DATE DE NAISSANCE | ASSEDIC | DC_STRUCTUREPRINCIPALEDE | DC_AGENTREFERENT
    # DC_STRUCTURERATTACH | DC_NOMAGENTREFERENT | DC_MAIL | DC_LBLPOSITIONNEMENTIAE
    df = pd.read_excel(
        import_file,
        converters={
            "NIR": str,
            "DC_NOMAGENTREFERENT": str,
            "DC_MAIL": str,
        },
    )

    df = df.rename(columns={"NIR": "nir", "DC_NOMAGENTREFERENT": "prescriber_name", "DC_MAIL": "prescriber_email"})
    df = df[["nir", "prescriber_name", "prescriber_email"]]
    df = df.dropna(subset=["prescriber_name", "prescriber_email"])
    logger.info(f"Found {len(df)} rows from GPS export.")

    nir_to_contact = {}
    count_nir_invalid_length = 0
    for row in df.itertuples():
        nir = row.nir
        match len(nir):
            case 13:
                # not all of the NIRs in the dataset are complete, so we treat them
                nir = f"{nir}{str(97 - int(nir) % 97).zfill(2)}"
            case 15:
                pass
            case _:
                count_nir_invalid_length += 1
                continue
        contact_details = FranceTravailContactDetails(row.prescriber_name, row.prescriber_email)
        existing = nir_to_contact.setdefault(nir, contact_details)
        if existing != contact_details:
            logger.warning(
                f"JobSeekerProfile with nir {nir} matched an additional contact that have not been imported."
            )

    if count_nir_invalid_length:
        logger.warning(f"There are {count_nir_invalid_length} included NIR values of invalid length after treatment.")

    cache.set(GPS_ADVISORS_KEY, nir_to_contact)
    return nir_to_contact


def create_or_update_advisor(jobseeker_profile, nir_to_contact, commit=True):
    if jobseeker_profile.nir not in nir_to_contact:
        return None, False

    contact_name, contact_email = nir_to_contact[jobseeker_profile.nir]
    created = False
    # prepare to create or update FranceTravailContact
    try:
        advisor = jobseeker_profile.advisor_information
        advisor.name = contact_name
        advisor.email = contact_email
    except FranceTravailContact.DoesNotExist:
        advisor = FranceTravailContact(
            name=contact_name,
            email=contact_email,
            jobseeker_profile=jobseeker_profile,
        )
        created = True
    if commit:
        advisor.save()

    return advisor, created


def find_job_seeker_advisor(jobseeker_profile):
    if not jobseeker_profile.nir:
        return

    nir_to_contact = cache.get(GPS_ADVISORS_KEY)

    # No cache available : wait for the next cron call (in less than 15 minutes)
    if nir_to_contact is None:
        return

    create_or_update_advisor(jobseeker_profile, nir_to_contact)
