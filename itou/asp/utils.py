from django.forms import ValidationError

from itou.asp.models import Commune, Country
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
