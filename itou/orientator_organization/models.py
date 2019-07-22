from django.db import models
from django.utils.translation import ugettext_lazy as _


class OrientatorOrganization(models.Model):
    """Structures d'accompagnement (orienteur/prescripteur)."""

    siret = models.CharField(verbose_name=_(u"Siret"), max_length=14, primary_key=True)
    name = models.CharField(verbose_name=_(u"Nom"), max_length=256)
    address = models.CharField(verbose_name=_(u"Adresse"), max_length=256)
    phone = models.CharField(verbose_name=_(u"Téléphone"), max_length=14)
    email = models.EmailField(verbose_name=_(u"E-mail"))

    class Meta:
        verbose_name = _(u"Structure d'accompagnement")
        verbose_name_plural = _(u"Structures d'accompagnement")

    def __str__(self):
        return f"{self.siret} {self.name}"
