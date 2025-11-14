import re

import html5lib
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.utils import timezone

from itou.utils.france_standards import NIR


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
    if not pole_emploi_id.isascii():
        raise ValidationError("L’identifiant France Travail ne doit pas contenir de caractères spéciaux.")
    is_old_format = len(pole_emploi_id) == 8 and pole_emploi_id[:7].isdigit() and pole_emploi_id[7:].isalnum()
    is_new_format = len(pole_emploi_id) == 11 and pole_emploi_id.isdigit()
    if not (is_new_format or is_old_format):
        raise ValidationError("Le format de l’identifiant France Travail est invalide.")


def validate_nir(nir):
    nir = NIR(nir)
    if len(nir) > 15:
        raise ValidationError("Le numéro de sécurité sociale est trop long (15 caractères autorisés).")
    if len(nir) < 15:
        raise ValidationError("Le numéro de sécurité sociale est trop court (15 caractères autorisés).")
    if not nir.is_valid():
        raise ValidationError("Ce numéro n'est pas valide.")

    if nir == "269054958815780":
        raise ValidationError("Ce numéro est fictif et indiqué à titre illustratif. Veuillez indiquer un numéro réel.")


def get_min_birthdate():
    return timezone.localdate() - relativedelta(years=100)


def get_max_birthdate():
    return timezone.localdate() - relativedelta(years=16)


def validate_birthdate(birthdate):
    if birthdate < get_min_birthdate():
        raise ValidationError("La personne doit avoir moins de 100 ans.")
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
