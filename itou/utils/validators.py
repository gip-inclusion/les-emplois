from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

alphanumeric = RegexValidator(
    r"^[0-9a-zA-Z]*$", "Seuls les caractères alphanumériques sont autorisés."
)


def validate_post_code(post_code):
    if not post_code.isdigit() or len(post_code) != 5:
        raise ValidationError(_("Le code postal doit être composé de 5 chiffres."))


def validate_siret(siret):
    if not siret.isdigit() or len(siret) != 14:
        raise ValidationError(_("Le numéro SIRET doit être composé de 14 chiffres."))


def validate_naf(naf):
    if len(naf) != 5 or not naf[:4].isdigit() or not naf[4].isalpha():
        raise ValidationError(
            _("Le code NAF doit être composé de de 4 chiffres et d'une lettre.")
        )


def validate_pole_emploi_id(pole_emploi_id):
    is_valid = (
        len(pole_emploi_id) == 8
        and pole_emploi_id[:7].isdigit()
        and pole_emploi_id[7:].isalnum()
    )
    if not is_valid:
        raise ValidationError(
            _(
                "L'identifiant Pôle emploi doit être composé de 8 caractères : "
                "7 chiffres suivis d'une 1 lettre ou d'un chiffre."
            )
        )
