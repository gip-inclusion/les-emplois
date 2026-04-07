from django.forms import ValidationError

from itou.asp.constants import ASP_COMMUNES_AS_COUNTRIES
from itou.asp.models import Commune, Country
from itou.asp.typing import AspBirthPlace
from itou.users.models import JobSeekerProfile
from itou.utils.validators import validate_nir


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
