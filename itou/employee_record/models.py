from django.db import models
from django.utils.translation import gettext_lazy as _

import itou.utils.validators as validators


class Status(models.TextChoices):
    NEW = "NEW", "Nouvelle fiche salarié"
    COMPLETE = "COMPLETE", "Données complètes"
    SENT = "SENT", "Envoyée ASP"
    REFUSED = "REFUSED", "Rejet ASP"
    PROCESSED = "PROCESSED", "Traitée ASP"


class EmployeeRecord(models.Model):

    approval = models.ForeignKey(
        "approvals.approval", null=True, on_delete=models.SET_NULL, verbose_name=_("PASS IAE")
    )
    siae = models.ForeignKey("siaes.siae", null=True, on_delete=models.SET_NULL, verbose_name=_("SIAE"))

    created_at = models.DateTimeField(verbose_name=("Date de création"))
    updated_at = models.DateTimeField(verbose_name=("Date de modification"))

    status = models.CharField(max_length=10, verbose_name=_("Statut"), choices=Status.choices, default=Status.NEW)

    class Meta:
        verbose_name = _("Fiche salarié")
        verbose_name_plural = _("Fiches salarié")
