import datetime
import re

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


alphanumeric = RegexValidator(r"^[0-9a-zA-Z]*$", _("Seuls les caractères alphanumériques sont autorisés."))


validate_code_safir = RegexValidator(r"^[0-9]{5}$", _("Le code SAFIR doit être composé de 5 chiffres."))


def validate_post_code(post_code):
    if not post_code.isdigit() or len(post_code) != 5:
        raise ValidationError(_("Le code postal doit être composé de 5 chiffres."))


def validate_siren(siren):
    if not siren.isdigit() or len(siren) != 9:
        raise ValidationError(_("Le numéro SIREN doit être composé de 9 chiffres."))


def validate_siret(siret):
    if not siret.isdigit() or len(siret) != 14:
        raise ValidationError(_("Le numéro SIRET doit être composé de 14 chiffres."))


def validate_naf(naf):
    if len(naf) != 5 or not naf[:4].isdigit() or not naf[4].isalpha():
        raise ValidationError(_("Le code NAF doit être composé de de 4 chiffres et d'une lettre."))


def validate_pole_emploi_id(pole_emploi_id):
    is_valid = len(pole_emploi_id) == 8 and pole_emploi_id[:7].isdigit() and pole_emploi_id[7:].isalnum()
    if not is_valid:
        raise ValidationError(
            _(
                "L'identifiant Pôle emploi doit être composé de 8 caractères : "
                "7 chiffres suivis d'une 1 lettre ou d'un chiffre."
            )
        )


def get_min_birthdate():
    return datetime.date(1900, 1, 1)


def get_max_birthdate():
    return timezone.now().date() - relativedelta(years=16)


def validate_birthdate(birthdate):
    if birthdate < get_min_birthdate():
        raise ValidationError(_("La date de naissance doit être postérieure à 1900."))
    if birthdate >= get_max_birthdate():
        raise ValidationError(_("La personne doit avoir plus de 16 ans."))


AF_NUMBER_PREFIX_REGEXPS = [
    # e.g. ACI063170007
    r"ACI\d{2}[A-Z\d]\d{6}",
    # e.g. EI080180002
    # e.g. EI59V182019
    r"EI\d{2}[A-Z\d]\d{5}",
    # e.g. AI088160001
    r"AI\d{2}[A-Z\d]\d{5}",
    # e.g. ETTI080180002
    # e.g. ETTI59L181001
    r"ETTI\d{2}[A-Z\d]\d{6}",
    r"EITI\d{2}[A-Z\d]\d{6}",
]


def validate_af_number(af_number):
    """
    Validate a SiaeFinancialAnnex number.
    """
    suffix = af_number[-4:]  # last 4 characters
    # e.g. A0M0, A0M1, A1M0.
    if not re.match(r"A\dM\d", suffix):
        raise ValidationError(_("Suffixe de numéro d'AF incorrect."))

    prefix = af_number[:-4]  # all but last 4 characters
    if not any([re.match(r, prefix) for r in AF_NUMBER_PREFIX_REGEXPS]):
        raise ValidationError(_("Préfixe de numéro d'AF incorrect."))


CONVENTION_NUMBER_REGEXPS = [
    # e.g. 063010517ACI00007
    # e.g. 59L010118ACI01001
    r"\d{2}[A-Z\d]\d{6}ACI\d{5}",
    # e.g. 047010117ACI0001003
    r"\d{9}ACI\d{7}",
    # e.g. 088010116AI00001
    # e.g. 59L010118AI01001
    r"\d{2}[A-Z\d]\d{6}AI\d{5}",
    # e.g. EI080180002
    # e.g. EI59V182019
    r"EI\d{2}[A-Z\d]\d{6}",
    # e.g. ETTI080180002
    # e.g. ETTI59L181001
    r"ETTI\d{2}[A-Z\d]\d{6}",
    # e.g. EITI076200002
    r"EITI\d{2}[A-Z\d]\d{6}",
]


def validate_convention_number(convention_number):
    if not any([re.match(r, convention_number) for r in CONVENTION_NUMBER_REGEXPS]):
        raise ValidationError(_("Numéro de convention incorrect."))
