from django.utils import crypto

from itou.utils.apis.api_entreprise import renew_password
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def handle(self, **options):
        # Allow to renew the password through the API (it's the only way)
        # See the API documentation
        # https://portail-api.insee.fr/catalog/api/26d13266-689d-3fee-845d-c08e12b8f0dd/doc?page=a7e0ed84-020c-48bc-a0ed-84020c08bce2

        # Only 13 special characters are allowed
        # We will not use $ as it causes issues when used in environment variables
        ALLOWED_SPECIAL_CHARACTERS = "@#^&*-_!+=?."
        new_password = crypto.get_random_string(30, crypto.RANDOM_STRING_CHARS + ALLOWED_SPECIAL_CHARACTERS)
        self.stdout.write(f"Tentative de modification du mot de passe en : {new_password}")
        self.stdout.write("...")

        success, error = renew_password(new_password)
        if success:
            self.stdout.write(
                "Mot de passe modifié. Mettez-le à jour dans settings et dans le gestionnaire de mot de passe."
            )
        else:
            self.stdout.write(error)
