from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.address.models import AddressMixin
from itou.utils.validators import validate_naf, validate_siret


class SiaeDefaultManager(models.Manager):

    def within(self, point, distance_km):
        return (self
            .filter(coords__distance_lte=(point, D(km=distance_km)))
            .annotate(distance=Distance('coords', point))
            .order_by('distance')
        )


class SiaeActiveManager(SiaeDefaultManager):

    def get_queryset(self):
        return super().get_queryset().filter(department__in=settings.ITOU_TEST_DEPARTMENTS)


class Siae(AddressMixin):
    """Structures d'insertion par l'activité économique."""

    KIND_EI = 'EI'
    KIND_AI = 'AI'
    KIND_ACI = 'ACI'
    KIND_ETTI = 'ETTI'
    KIND_GEIQ = 'GEIQ'
    KIND_RQ = 'RQ'

    KIND_CHOICES = (
        (KIND_EI, _("Entreprise d'insertion")),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, _("Association intermédiaire")),
        (KIND_ACI, _("Atelier chantier d'insertion")),
        (KIND_ETTI, _("Entreprises de travail temporaire d'insertion")),
        (KIND_GEIQ, _("Groupement d'employeurs pour l'insertion et la qualification")),
        (KIND_RQ, _("Régie de quartier")),
    )

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret], primary_key=True)
    naf = models.CharField(verbose_name=_("Naf"), max_length=5, validators=[validate_naf])
    kind = models.CharField(verbose_name=_("Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name=_("Nom"), max_length=256)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=10, blank=True)
    email = models.EmailField(verbose_name=_("E-mail"), blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name=_("Membres"),
        through='SiaeMembership', blank=True)

    objects = SiaeDefaultManager()
    active_objects = SiaeActiveManager()

    class Meta:
        verbose_name = _("Structure d'insertion par l'activité économique")
        verbose_name_plural = _("Structures d'insertion par l'activité économique")

    def __str__(self):
        return f"{self.siret} {self.name}"

    def get_card_url(self):
        return reverse('siae:card', kwargs={'siret': self.siret})


class SiaeMembership(models.Model):
    """Intermediary model between `User` and `Siae`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    siae = models.ForeignKey(Siae, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name=_("Date d'adhésion"), default=timezone.now)
    is_siae_admin = models.BooleanField(verbose_name=_("Administrateur de la SIAE"), default=False)
