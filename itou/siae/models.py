from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.address.models import AddressMixin
from itou.utils.validators import validate_naf, validate_siret


class Siae(AddressMixin):
    """Structures d'insertion par l'activité économique."""

    KIND_EI = 'EI'
    KIND_AI = 'AI'
    KIND_ACI = 'ACI'
    KIND_ETTI = 'ETTI'
    KIND_GEIQ = 'GEIQ'
    KIND_RQ = 'RQ'

    KIND_CHOICES = (
        (KIND_EI, _("Entreprises d'insertion")),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, _("Associations intermédiaires")),
        (KIND_ACI, _("Ateliers chantiers d'insertion")),
        (KIND_ETTI, _("Entreprises de travail temporaire d'insertion")),
        (KIND_GEIQ, _("Groupements d'employeurs pour l'insertion et la qualification")),
        (KIND_RQ, _("Régies de quartier")),
    )

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret], primary_key=True)
    naf = models.CharField(verbose_name=_("Naf"), max_length=5, validators=[validate_naf])
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name=_("Nom"), max_length=256)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=10)
    email = models.EmailField(verbose_name=_("E-mail"))
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name=_("Membres"),
        through='SiaeMembership', blank=True)

    class Meta:
        verbose_name = _("Structure d'insertion par l'activité économique")
        verbose_name_plural = _("Structures d'insertion par l'activité économique")

    def __str__(self):
        return f"{self.siret} {self.name}"


class SiaeMembership(models.Model):
    """Intermediary model between `User` and `Siae`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name=_("Date d'adhésion"), default=timezone.now)
    is_siae_admin = models.BooleanField(verbose_name=_("Administrateur de la SIAE"), default=False)
