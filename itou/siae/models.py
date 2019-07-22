from django.db import models
from django.utils.translation import ugettext_lazy as _


class Siae(models.Model):
    """Structures d'insertion par l'activité économique."""

    KIND_EI = 'EI'
    KIND_AI = 'AI'
    KIND_ACI = 'ACI'
    KIND_ETTI = 'ETTI'
    KIND_GEIQ = 'GEIQ'
    KIND_RQ = 'RQ'

    KIND_CHOICES = (
        (KIND_EI, _(u"Entreprises d'insertion")),  # Regroupées au sein de la fédération des entreprises d'insertion.
        (KIND_AI, _(u"Associations intermédiaires")),
        (KIND_ACI, _(u"Ateliers chantiers d'insertion")),
        (KIND_ETTI, _(u"Entreprises de travail temporaire d'insertion")),
        (KIND_GEIQ, _(u"Groupements d'employeurs pour l'insertion et la qualification")),
        (KIND_RQ, _(u"Régies de quartier")),
    )

    siret = models.CharField(verbose_name=_(u"Siret"), max_length=14, primary_key=True)
    kind = models.CharField(verbose_name=_(u"Type"), max_length=4, choices=KIND_CHOICES, default=KIND_EI)
    name = models.CharField(verbose_name=_(u"Nom"), max_length=256)
    activities = models.CharField(verbose_name=_(u"Secteur d'activités"), max_length=256)
    address = models.CharField(verbose_name=_(u"Adresse"), max_length=256)
    phone = models.CharField(verbose_name=_(u"Téléphone"), max_length=14)
    email = models.EmailField(verbose_name=_(u"E-mail"))

    class Meta:
        verbose_name = _(u"Structure d'insertion par l'activité économique")
        verbose_name_plural = _(u"Structures d'insertion par l'activité économique")

    def __str__(self):
        return f"{self.siret} {self.name}"
