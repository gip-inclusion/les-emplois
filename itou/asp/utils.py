import logging

from django.db.models import Q
from django.forms import ValidationError

from itou.asp.constants import ASP_COMMUNES_AS_COUNTRIES
from itou.asp.models import Commune, Country
from itou.asp.typing import AspBirthPlace
from itou.users.models import JobSeekerProfile
from itou.utils.validators import validate_nir


logger = logging.getLogger(__name__)


def guess_birth_place_from_nir(nir: str) -> tuple[Commune | None, Country | None]:
    # Errors (invalid NIR, invalid country/commmune code, etc.) are
    # ignored: we silently return None for one or both values.
    nir = nir.replace(" ", "")
    try:
        validate_nir(nir)
    except ValidationError:
        return None, None

    # We may receive a NIA ("numéro d'identification en attente") that
    # starts with "3", "4", "7" or "8". From what we can gather from
    # our database, NIA that start with "3" or "4" may be reliable.
    # However, those that start with "7" or "8" are probably not
    # reliable.
    if nir.startswith(("7", "8")):
        return None, None

    department_code = nir[5:7]

    if department_code == "99":
        city = None
        country_code = nir[7:10]
        country = Country.objects.filter(code=country_code).first()
    else:
        city_code = nir[5:10]
        city = Commune.objects.filter(code=city_code).first()
        country = Country.objects.get(id=Country.FRANCE_ID)

    return city, country


def asp_birth_place(job_seeker_profile: JobSeekerProfile) -> AspBirthPlace:
    birth_place = job_seeker_profile.birth_place
    birth_country = job_seeker_profile.birth_country
    # The birth_place is empty if the candidate is not born in
    # France. In that case, send special department code "099"
    # (error 3411).
    if not birth_place:
        return {
            "codeComInsee": {
                "codeComInsee": None,
                "codeDpt": "099",
            },
            "codeInseePays": birth_country.code if birth_country else None,
        }

    # ASP has a special rule for some places in Nouvelle-Calédonie,
    # Polynésie, etc.
    if code_of_commune_as_country := ASP_COMMUNES_AS_COUNTRIES.get(birth_place.name):
        return {
            "codeComInsee": {
                "codeComInsee": None,
                "codeDpt": "099",
            },
            "codeInseePays": code_of_commune_as_country,
        }

    return {
        "codeComInsee": {
            "codeComInsee": birth_place.code,
            "codeDpt": birth_place.department_code,
        },
        "codeInseePays": birth_country.code,
    }


def migrate_commune(obsolete_commune, target_code, *, commune_model=None, job_seeker_profile_model=None):
    # To ease the use of the function in migrations
    if commune_model is None:
        commune_model = Commune
    if job_seeker_profile_model is None:
        job_seeker_profile_model = JobSeekerProfile

    if obsolete_commune is None:
        # The commune doesn't exist on this system: nothing to do
        return
    if target_code is not None:
        profiles_to_update = list(job_seeker_profile_model.objects.filter(birth_place=obsolete_commune))
        # If the target is empty, keep the current commune, since removing the info won't solve anything
        for profile in profiles_to_update:
            if profile.birthdate:
                profile.birth_place = commune_model.objects.filter(
                    Q(start_date__lte=profile.birthdate, end_date__gte=profile.birthdate)
                    | Q(start_date__lte=profile.birthdate, end_date__isnull=True),
                    code=target_code,
                ).first()
            else:
                profile.birth_place = commune_model.objects.filter(
                    end_date__isnull=True,
                    code=target_code,
                ).first()
            if profile.birth_place is None:
                # This shouldn't happen but make sure the migration doesn't crash
                profile.birth_country = None
                logger.error(
                    "migrating profile=%d from birth commune=%s to target_code=%s removed the birth place/country",
                    profile.pk,
                    obsolete_commune,
                    target_code,
                )
            else:
                logger.info(
                    "migrated profile=%d from birth commune=%s to target_code=%s (birth_place=%s)",
                    profile.pk,
                    obsolete_commune,
                    target_code,
                    profile.birth_place,
                )
        JobSeekerProfile.objects.bulk_update(profiles_to_update, ["birth_place", "birth_country"])

    if target_code is not None:
        # If the target is empty, keep the current commune, since it should still be accepted by the ASP
        # (while None would make the employee record invalid)
        new_commune = commune_model.objects.filter(end_date__isnull=True, code=target_code).first()
        if new_commune:
            # Same logic, only update profiles if a new commune is available
            profile_ids_to_update = []
            for profile in job_seeker_profile_model.objects.filter(hexa_commune=obsolete_commune):
                logger.info(
                    "migrated profile=%d from hexa commune=%s to target_code=%s (hexa_commune=%s)",
                    profile.pk,
                    obsolete_commune,
                    target_code,
                    new_commune,
                )
                profile_ids_to_update.append(profile.pk)
            JobSeekerProfile.objects.filter(user_id__in=profile_ids_to_update).update(hexa_commune=new_commune)

    if not obsolete_commune.ignore:
        logger.info("ignore flag added to commune=%s", obsolete_commune)
        obsolete_commune.ignore = True
        obsolete_commune.save(update_fields={"ignore"})
