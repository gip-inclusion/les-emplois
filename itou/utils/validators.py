import datetime
import re

import html5lib
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.utils import timezone


alphanumeric = RegexValidator(r"^[0-9a-zA-Z]*$", "Seuls les caractères alphanumériques sont autorisés.")


validate_code_safir = RegexValidator(r"^[0-9]{5}$", "Le code SAFIR doit être composé de 5 chiffres.")


def validate_post_code(post_code):
    if not post_code.isdigit() or len(post_code) != 5:
        raise ValidationError("Le code postal doit être composé de 5 chiffres.")


def validate_siren(siren):
    if not siren.isdigit() or len(siren) != 9:
        raise ValidationError("Le numéro SIREN doit être composé de 9 chiffres.")


def validate_siret(siret):
    if not siret.isdigit() or len(siret) != 14:
        raise ValidationError("Le numéro SIRET doit être composé de 14 chiffres.")


def validate_naf(naf):
    if len(naf) != 5 or not naf[:4].isdigit() or not naf[4].isalpha():
        raise ValidationError("Le code NAF doit être composé de de 4 chiffres et d'une lettre.")


def validate_pole_emploi_id(pole_emploi_id):
    is_valid = len(pole_emploi_id) == 8 and pole_emploi_id[:7].isdigit() and pole_emploi_id[7:].isalnum()
    if not is_valid:
        raise ValidationError(
            "L'identifiant France Travail (ex pôle emploi) doit être composé de 8 caractères : "
            "7 chiffres suivis d'une 1 lettre ou d'un chiffre."
        )


def validate_nir(nir):
    # http://nourtier.net/cle_NIR/cle_NIR.htm
    nir = str(nir).replace(" ", "").upper()
    # Replace 2A and 2B by 19 and 18 to handle digits.
    nir = nir.replace("2A", "19").replace("2B", "18")
    if len(nir) > 15:
        raise ValidationError("Le numéro de sécurité sociale est trop long (15 caractères autorisés).")
    if len(nir) < 15:
        raise ValidationError("Le numéro de sécurité sociale est trop court (15 caractères autorisés).")
    # Warning : any change to this regex must be reflected on format filter "format_nir"
    nir_regex = r"^[12][0-9]{2}[0-9]{2}(2[AB]|[0-9]{2})[0-9]{3}[0-9]{3}[0-9]{2}$"

    match = re.match(nir_regex, nir)
    if not match:
        raise ValidationError("Ce numéro n'est pas valide.")

    # For the month of birth, fictitious codes are assigned for persons registered on the basis of an incomplete civil
    # status certificate. A valid month can also be between 20 and 42 or between 50 and 99.
    # Source : https://fr.wikipedia.org/wiki/Num%C3%A9ro_de_s%C3%A9curit%C3%A9_sociale_en_France#ancrage_B
    month = int(nir[3:5])
    if (month > 12 and month < 20) or (month > 42 and month < 50):
        raise ValidationError("Ce numéro n'est pas valide.")

    # Last 2 digits validate previous 13 characters.
    control_key = int(nir[-2:])
    if control_key != (97 - int(nir[:13]) % 97):
        raise ValidationError("Ce numéro n'est pas valide.")

    if nir == "269054958815780":
        raise ValidationError("Ce numéro est fictif et indiqué à titre illustratif. Veuillez indiquer un numéro réel.")


def get_min_birthdate():
    return datetime.date(1900, 1, 1)


def get_max_birthdate():
    return timezone.localdate() - relativedelta(years=16)


def validate_birthdate(birthdate):
    if birthdate < get_min_birthdate():
        raise ValidationError("La date de naissance doit être postérieure à 1900.")
    if birthdate >= get_max_birthdate():
        raise ValidationError("La personne doit avoir plus de 16 ans.")


AF_NUMBER_PREFIX_REGEXPS = [
    r"^ACI\d{2}[A-Z\d]\d{6}$",
    r"^EI\d{2}[A-Z\d]\d{6}$",
    r"^AI\d{2}[A-Z\d]\d{6}$",
    r"^ETTI\d{2}[A-Z\d]\d{6}$",
    r"^EITI\d{2}[A-Z\d]\d{6}$",
]


def validate_af_number(af_number):
    """
    Validate a SiaeFinancialAnnex number.
    """
    if not af_number or len(af_number) <= 4:
        raise ValidationError("Numéro d'AF vide ou trop court")
    suffix = af_number[-4:]  # last 4 characters
    # e.g. A0M0, A0M1, A1M0.
    if not re.match(r"^A\dM\d$", suffix):
        raise ValidationError("Suffixe de numéro d'AF incorrect.")

    prefix = af_number[:-4]  # all but last 4 characters
    if not any([re.match(r, prefix) for r in AF_NUMBER_PREFIX_REGEXPS]):
        raise ValidationError("Préfixe de numéro d'AF incorrect.")


def validate_html(html):
    if "<script" in html:
        raise ValidationError("Balise script interdite.")

    try:
        html5lib.HTMLParser(strict=True).parseFragment(html)
    except html5lib.html5parser.ParseError as exc:
        raise ValidationError("HTML invalide.") from exc


def reformat_limit_date(exc):
    params = exc.params.copy()
    params["limit_value"] = f"{params['limit_value']:%d/%m/%Y}"
    return ValidationError(exc.message, code=exc.code, params=params)


class MinDateValidator(MinValueValidator):
    def __call__(self, value):
        try:
            super().__call__(value)
        except ValidationError as e:
            raise reformat_limit_date(e) from e


class MaxDateValidator(MaxValueValidator):
    def __call__(self, value):
        try:
            super().__call__(value)
        except ValidationError as e:
            raise reformat_limit_date(e) from e
