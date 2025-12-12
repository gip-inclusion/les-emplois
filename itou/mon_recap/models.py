from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from itou.mon_recap.enums import NotebookOrderKind


def validate_amount_wished(amount):
    if amount not in [2, 15, 40, 60, 100, 140, 200, 300, 400, 500]:
        raise ValidationError("Le nombre de carnets souhaité ne fait pas partie de la liste des valeurs autorisées")


class NotebookOrder(models.Model):
    created_at = models.DateTimeField(verbose_name="créé le")
    email = models.EmailField()
    is_in_priority_department = models.BooleanField(verbose_name="se trouve dans un département prioritaire")
    is_first_order = models.BooleanField(verbose_name="première commande de l'organisation")
    is_first_order_in_department = models.CharField(
        verbose_name="première commande dans le départment de l'organisation"
    )
    organization_name = models.CharField(verbose_name="nom de l'organisation")
    organization_type = models.CharField(verbose_name="type de l'organisation")
    organization_is_in_network = models.BooleanField(verbose_name="organisation appartient à un réseau, groupe, label")
    organization_network = ArrayField(models.CharField(), null=True, verbose_name="réseau de l'organisation")
    organization_is_in_qpv_or_zrr = models.CharField(verbose_name="organisation située dans en QPV ou ZRR")
    role = models.CharField(verbose_name="fonction du demandeur")
    coworkers_will_distribute = models.BooleanField(
        verbose_name="si d'autres accompagnateurs distribueront les carnets"
    )
    coworkers_emails = ArrayField(models.EmailField(), null=True, verbose_name="emails des accompagnateurs")
    source = models.CharField(verbose_name="source par laquelle le demandeur a découvert Mon Récap")
    source_details = models.CharField(null=True, verbose_name="détails sur la source")
    kind = models.CharField(choices=NotebookOrderKind.choices, verbose_name="type de commande")
    unit_price = models.IntegerField(verbose_name="prix d'un carnet")
    amount = models.IntegerField(verbose_name="quantité de carnets")
    previous_notebooks_out_of_stock = models.BooleanField(
        null=True, verbose_name="si les précédents carnets sont épuisés"
    )
    financing_likelihood = models.IntegerField(
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name="probabilité de financer l'achat d'autres carnets à l'avenir",
    )
    financing_obstacles = models.TextField(null=True, verbose_name="freins au financement")
    users_are_autonomous = models.BooleanField(null=True, verbose_name="si les publics visés sont autonomes")
    users_need_tools = models.BooleanField(null=True, verbose_name="si les publics visés ont besoin d'outils")
    users_have_obstacles = models.BooleanField(null=True, verbose_name="si les publics visés ont des freins")
    most_recurring_obstacles = models.TextField(null=True, verbose_name="freins les plus récurrents")
    reason = models.CharField(null=True, verbose_name="précision sur refus de financement")
    amount_wished = models.IntegerField(
        validators=[validate_amount_wished], verbose_name="quantité de carnets souhaitée"
    )
    full_name = models.CharField(verbose_name="nom et prénom")
    address = models.CharField(verbose_name="addresse")
    siret = models.CharField(verbose_name="siret")
    city = models.CharField(verbose_name="ville")
    post_code = models.CharField(verbose_name="code postal")
    phone_number = models.CharField(verbose_name="téléphone")
