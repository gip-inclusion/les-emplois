from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.backends.postgresql.psycopg_any import NumericRange
from django_xworkflows import models as xwf_models

from itou.mon_recap import enums
from itou.utils.validators import validate_post_code, validate_siret


def validate_quantity_requested(amount):
    if amount not in [2, 15, 40, 60, 100, 140, 200, 300, 400, 500]:
        raise ValidationError("Le nombre de carnets souhaité ne fait pas partie de la liste des valeurs autorisées")


class WebhookEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="créé le")
    body = models.JSONField(editable=False)
    headers = models.JSONField(editable=False)
    is_processed = models.BooleanField(default=False, editable=False)

    class Meta:
        verbose_name = "événement du webhook Mon Récap"
        verbose_name_plural = "événements du webhook Mon Récap"


class Organization(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="créée le")
    name = models.CharField(max_length=255, verbose_name="nom")
    siret = models.CharField(max_length=14, validators=[validate_siret], unique=True, verbose_name="SIRET")
    kind = models.CharField(choices=enums.OrganizationKind, verbose_name="type")
    other_kind = models.CharField(max_length=150, blank=True, verbose_name="autre type")
    is_in_network = models.BooleanField(verbose_name="membre d'un réseau")
    networks = ArrayField(models.CharField(choices=enums.OrganizationNetwork), default=list, verbose_name="réseau")
    other_network = models.CharField(max_length=150, blank=True, verbose_name="autre réseau")
    is_in_qpv = models.BooleanField(verbose_name="située en QPV")
    is_in_zrr = models.BooleanField(verbose_name="située en ZRR")
    email = models.EmailField(verbose_name="e-mail")

    class Meta:
        verbose_name = "organisation Mon Récap"
        verbose_name_plural = "organisations Mon Récap"


class OrganizationAddress(models.Model):
    full_name = models.CharField(verbose_name="nom et prénom")
    street_address = models.CharField(verbose_name="rue")
    city = models.CharField(verbose_name="ville")
    post_code = models.CharField(max_length=5, validators=[validate_post_code], verbose_name="code postal")
    phone = models.CharField(max_length=20, verbose_name="téléphone")

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name="organisation",
    )


class NotebookOrderWorkflow(xwf_models.Workflow):
    """
    The JobApplication workflow.
    https://django-xworkflows.readthedocs.io/
    """

    states = enums.NotebookOrderState.choices
    initial_state = enums.NotebookOrderState.NEW


class NotebookOrder(xwf_models.WorkflowEnabled, models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="créée le")
    state = xwf_models.StateField(NotebookOrderWorkflow, db_index=True, verbose_name="état")
    # FIXME(kind): source=Tally, confusion between type and status
    kind = models.CharField(choices=enums.NotebookOrderKind, editable=False, verbose_name="type de commande")
    requested_at = models.DateTimeField(verbose_name="demandé le")
    requester_kind = models.CharField(choices=enums.RequesterKind, verbose_name="type de demandeur")
    unit_price = models.DecimalField(max_digits=4, decimal_places=2, verbose_name="prix d'un carnet")
    quantity_requested = models.IntegerField(
        validators=[validate_quantity_requested], verbose_name="quantité de carnets souhaitée"
    )
    quantity_delivered = models.IntegerField(null=True, verbose_name="quantité de carnets délivrée")

    is_previous_order_out_of_stock = models.BooleanField(
        null=True, verbose_name="la précédente commande est épuisée ?"
    )
    is_in_priority_department = models.BooleanField(verbose_name="dans un département prioritaire ?")
    is_organization_first_order = models.BooleanField(verbose_name="première commande de l'organisation ?")
    is_organization_first_order_in_department = models.BooleanField(
        null=True, verbose_name="première commande dans le départment de l'organisation ?"
    )
    with_coworkers_distribution = models.BooleanField(verbose_name="carnets distribués par des accompagnateurs ?")
    coworkers_emails = ArrayField(
        models.EmailField(), null=True, default=list, verbose_name="e-mails des accompagnateurs"
    )
    source = models.CharField(
        choices=enums.DiscoverySource, verbose_name="comment le demandeur a découvert Mon Récap ?"
    )
    other_source = models.CharField(blank=True, verbose_name="autre source")

    supply_motivation = models.TextField(blank=True, max_length=2000, verbose_name="motivation à équiper les usagers")
    financing_intent = models.SmallIntegerField(
        default=(-1),
        validators=[MinValueValidator(-1), MaxValueValidator(10)],
        verbose_name="probabilité de financer l'achat de carnets à l'avenir",
    )
    financing_obstacles = models.TextField(blank=True, max_length=2000, verbose_name="freins au financement")

    public_is_autonomous = models.BooleanField(verbose_name="le public accompagné est autonome ?")
    public_has_other_tools = models.BooleanField(verbose_name="le public accompagné a d'autres outils ?")
    public_has_obstacles = models.BooleanField(verbose_name="le public accompagné a plusieurs freins ?")
    public_main_obstacles = ArrayField(
        models.CharField(choices=enums.PublicObstacles),
        size=3,
        default=list,
        verbose_name="obstacles principaux du public accompagné",
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.RESTRICT,
        related_name="notebook_orders",
        verbose_name="organisation",
    )
    address = models.ForeignKey(
        OrganizationAddress,
        on_delete=models.RESTRICT,
        related_name="notebook_orders",
        verbose_name="adresse",
    )
    webhook_event = models.ForeignKey(
        WebhookEvent,
        on_delete=models.RESTRICT,
        editable=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="unique_organization_first_order",
                fields=["organization"],
                condition=models.Q(is_organization_first_order=True),
            ),
            models.UniqueConstraint(
                name="unique_organization_first_order_in_dpt",
                fields=["organization"],
                condition=models.Q(is_organization_first_order_in_department=True),
            ),
            models.CheckConstraint(
                name="coworkers_emails_coherence",
                violation_error_message="Incohérence au niveau des adresses e-mails des accompagnateurs",
                condition=(
                    models.Q(
                        with_coworkers_distribution=False,
                        requester_kind=enums.RequesterKind.COUNSELOR,
                        coworkers_emails__len=0,
                    )
                )
                | (
                    (models.Q(with_coworkers_distribution=True) | models.Q(requester_kind=enums.RequesterKind.MANAGER))
                    & ~models.Q(coworkers_emails__len=0)
                ),
            ),
            models.CheckConstraint(
                name="financing_intent_coherence",
                violation_error_message="Incohérence au niveau de la probabilité de financement",
                condition=models.Q(financing_intent=(-1), is_organization_first_order_in_department=False)
                | models.Q(
                    financing_intent__contained_by=NumericRange(0, 11), is_organization_first_order_in_department=True
                ),
            ),
            models.CheckConstraint(
                name="public_main_obstacles_coherence",
                violation_error_message="Incohérence au niveau des freins du public",
                condition=models.Q(public_has_obstacles=True, public_main_obstacles__len=3)
                | models.Q(public_has_obstacles=False, public_main_obstacles__len=0),
            ),
        ]
