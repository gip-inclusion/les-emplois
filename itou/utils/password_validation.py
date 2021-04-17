import string

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy


class CnilCompositionPasswordValidator:
    """
    Validate whether the password is conform to CNIL guidelines.

    CNIL guidelines regarding the use case "Avec restriction d'accès":
    https://www.cnil.fr/fr/authentification-par-mot-de-passe-les-mesures-de-securite-elementaires

    - Minimum length: at least 8 characters (handled via `MinimumLengthValidator`)
    - Composition: password must include 3 of the 4 types of characters
        1) uppercase
        2) lowercase
        3) numbers
        4) special characters
    - Additional measure: account access timeout after multiple failures (handled via `django-allauth`)

    This validator only checks for the "composition" part.
    """

    SPECIAL_CHARS = string.punctuation

    HELP_MSG = (
        "Le mot de passe doit contenir au moins 3 des 4 types suivants : "
        "majuscules, minuscules, chiffres, caractères spéciaux."
    )

    def validate(self, password, user=None):

        has_lower = any(char.islower() for char in password)
        has_upper = any(char.isupper() for char in password)
        has_digit = any(char.isdigit() for char in password)
        has_special_char = any(char in self.SPECIAL_CHARS for char in password)

        # Booleans are a subtype of integers.
        # https://docs.python.org/3/library/stdtypes.html#numeric-types-int-float-complex
        if (has_lower + has_upper + has_digit + has_special_char) < 3:
            raise ValidationError(self.HELP_MSG, code="cnil_composition")

    def get_help_text(self):
        return self.HELP_MSG
