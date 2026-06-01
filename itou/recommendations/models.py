import uuid

from citext import CIEmailField
from django.db import models

from itou.utils.validators import validate_code_safir, validate_france_travail_id_new_format


class Beneficiary(models.Model):
    """
    A class to store job seekers supported by a FT advisor.
    This a distinct class from User with `kind=job_seekers` because we are creating a beta feature.
    It will be easier to work within this app and merge in User model when everything is stable.
    """

    public_id = models.UUIDField(
        verbose_name="identifiant public",
        help_text="identifiant opaque, pour les URLs publiques",
        default=uuid.uuid4,
        unique=True,
    )

    # for display in the list view
    first_name = models.CharField(verbose_name="prénom", max_length=150, blank=True)
    last_name = models.CharField(verbose_name="nom de famille", max_length=150, blank=True)

    # Used to query FT APIs
    france_travail_id = models.CharField(
        verbose_name="identifiant France Travail",
        help_text="L’identifiant doit être composé de 11 chiffres.",
        max_length=11,
        validators=[validate_france_travail_id_new_format],
    )

    # Used to filter displayable job seeker for a given user
    referent_email = CIEmailField("adresse e-mail", db_index=True)
    organization_safir = models.CharField(
        verbose_name="code Safir",
        help_text="Code unique d'une agence France Travail.",
        validators=[validate_code_safir],
        max_length=5,
    )

    class Meta:
        verbose_name = "demandeur d'emploi"
        verbose_name_plural = "demandeurs d'emploi"

        constraints = [
            models.CheckConstraint(name="safir_format", condition=models.Q(organization_safir__regex=r"\A[0-9]{5}\Z")),
            models.CheckConstraint(
                name="france_travail_id_format", condition=models.Q(france_travail_id__regex=r"\A[0-9]{11}\Z")
            ),
        ]

    def get_inverted_full_name(self):
        """
        Return the last_name plus the first_name, with a space in between.
        """
        full_name = f"{self.last_name.upper()} {self.first_name.strip().title()}"
        return full_name.strip()
