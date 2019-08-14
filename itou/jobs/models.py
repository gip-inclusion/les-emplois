from django.db import models
from django.utils.translation import gettext_lazy as _


class Job(models.Model):
    """
    Data is provided via provided via `django-admin import_jobs`.
    """

    RIASEC_REALISTIC = 'R'
    RIASEC_INVESTIGATIVE = 'I'
    RIASEC_ARTISTIC = 'A'
    RIASEC_SOCIAL = 'S'
    RIASEC_ENTERPRISING = 'E'
    RIASEC_CONVENTIONAL = 'C'

    RIASEC_CHOICES = (
        (RIASEC_REALISTIC, _("Réaliste")),
        (RIASEC_INVESTIGATIVE, _("Investigateur")),
        (RIASEC_ARTISTIC, _("Artistique")),
        (RIASEC_SOCIAL, _("Social")),
        (RIASEC_ENTERPRISING, _("Entreprenant")),
        (RIASEC_CONVENTIONAL, _("Conventionnel")),
    )

    code_rome = models.CharField(verbose_name=_("Code ROME"), max_length=5, primary_key=True)
    name = models.CharField(verbose_name=_("Nom"), max_length=256, db_index=True)
    riasec_major = models.CharField(verbose_name=_("RIASEC Majeur"), max_length=1, choices=RIASEC_CHOICES,
        default=RIASEC_REALISTIC)
    riasec_minor = models.CharField(verbose_name=_("RIASEC Mineur"), max_length=1, choices=RIASEC_CHOICES,
        default=RIASEC_REALISTIC)
    code_isco = models.CharField(verbose_name=_("Code ROME"), max_length=4)

    class Meta:
        verbose_name = _("Métier")
        verbose_name_plural = _("Métiers")

    def __str__(self):
        return self.name


class Appellation(models.Model):
    """
    Data is provided via `django-admin import_appellations_for_jobs`.
    """

    code = models.CharField(verbose_name=_("Code"), max_length=6, primary_key=True)
    name = models.CharField(verbose_name=_("Nom"), max_length=256, db_index=True)
    short_name = models.CharField(verbose_name=_("Nom court"), max_length=256, db_index=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, null=True, related_name="appellations")

    class Meta:
        verbose_name = _("Appellation")
        verbose_name_plural = _("Appellations")

    def __str__(self):
        return self.name
