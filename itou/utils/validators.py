from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_siret(siret):
    if not siret.isdigit() or len(siret) != 14:
        raise ValidationError(_("Le numéro SIRET doit être composé de 14 chiffres."))


def validate_naf(naf):
    if len(naf) != 5 or not naf[:4].isdigit() or not naf[4].isalpha():
        raise ValidationError(
            _("Le code NAF doit être composé de de 4 chiffres et d'une lettre.")
        )


def validate_phone(phone):
    if not phone.isdigit() or len(phone) != 10:
        raise ValidationError(
            _("Le numéro de téléphone doit être composé de 10 chiffres.")
        )
