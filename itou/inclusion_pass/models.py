from uuid import uuid4

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationKind
from itou.companies.enums import (
    ProSupportReportAutonomy,
    ProSupportReportBarrier,
    ProSupportReportOrientation,
    ProSupportReportSolution,
)
from itou.inclusion_pass import catalogue


class Offreur(OrganizationAbstract):
    """Service provider outside the IAE (driving school, social grocery…), linked to its data·inclusion structure."""

    ORGANIZATION_KIND = OrganizationKind.OFFREUR
    KIND_DISPLAY = "Offreur de service"

    structure = models.OneToOneField(
        "insertion.Structure", verbose_name="structure d'insertion", on_delete=models.PROTECT, related_name="offreur"
    )
    # Public: encoded in the reception QR code displayed in the offreur premises
    uuid_accueil = models.UUIDField(default=uuid4, unique=True, editable=False)
    donnees_demandees = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="membres",
        through="OffreurMembership",
        blank=True,
        through_fields=("offreur", "user"),
    )

    class Meta:
        verbose_name = "offreur de service"
        verbose_name_plural = "offreurs de service"

    @property
    def kind(self):
        return self.KIND_DISPLAY


class OffreurMembership(MembershipAbstract):
    """Intermediary model between `User` and `Offreur`."""

    offreur = models.ForeignKey(Offreur, on_delete=models.CASCADE, related_name="memberships")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_offreurmembership_set",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        verbose_name="mis à jour par",
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "offreur"], name="user_offreur_unique")]

    def get_organization(self):
        return self.offreur


class Accompagnement(models.Model):
    personne = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pass_accompagnements"
    )
    offreur = models.ForeignKey(Offreur, on_delete=models.CASCADE, related_name="accompagnements")
    prescripteur = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pass_accompagnements",
    )
    orientation = models.ForeignKey(
        "insertion.Orientation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    vu_par_offreur = models.BooleanField(default=False)
    # Entry statuses captured for the impact report (RSA, job seeker, QPV)
    statuts_entree = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    @property
    def en_cours(self):
        return self.ended_at is None


class ConsentementQuerySet(models.QuerySet):
    def actifs(self):
        return self.filter(revoked_at=None)


class Consentement(models.Model):
    personne = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pass_consentements")
    offreur = models.ForeignKey(Offreur, on_delete=models.CASCADE, related_name="consentements")
    donnee = models.CharField(max_length=50)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = ConsentementQuerySet.as_manager()

    class Meta:
        ordering = ["-granted_at"]

    @property
    def libelle(self):
        return catalogue.libelle(self.donnee)


class DonneePartagee(models.Model):
    personne = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pass_donnees")
    donnee = models.CharField(max_length=50)
    valeur = models.JSONField(default=dict)
    source = models.CharField(max_length=255)
    fetched_at = models.DateTimeField(default=timezone.now)
    erreur = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["personne", "donnee"], name="pass_donnee_unique")]


class AccesDonnee(models.Model):
    class Action(models.TextChoices):
        OCTROI = "octroi", "Accord donné"
        RETRAIT = "retrait", "Accord retiré"
        RECUPERATION = "recuperation", "Donnée récupérée à la source"
        CONSULTATION = "consultation", "Donnée consultée"
        NOTIFICATION = "notification", "Conseiller prévenu"

    personne = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pass_acces")
    offreur = models.ForeignKey(Offreur, on_delete=models.CASCADE, null=True, blank=True)
    donnee = models.CharField(max_length=50)
    action = models.CharField(max_length=20, choices=Action.choices)
    source = models.CharField(max_length=255, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-at"]

    @property
    def libelle(self):
        return catalogue.libelle(self.donnee)


class SituationSuivi(models.Model):
    class Situation(models.TextChoices):
        EMPLOI = "emploi", "En emploi"
        FORMATION = "formation", "En formation"
        RECHERCHE = "recherche", "En recherche"

    accompagnement = models.ForeignKey(Accompagnement, on_delete=models.CASCADE, related_name="situations")
    mois = models.PositiveSmallIntegerField()
    situation = models.CharField(max_length=20, choices=Situation.choices)
    simule = models.BooleanField(default=True)

    class Meta:
        ordering = ["mois"]

    @property
    def est_positive(self):
        return self.situation in (self.Situation.EMPLOI, self.Situation.FORMATION)


class NotificationPrescripteur(models.Model):
    prescripteur = models.ForeignKey(
        "prescribers.PrescriberOrganization", on_delete=models.CASCADE, related_name="pass_notifications"
    )
    accompagnement = models.ForeignKey(Accompagnement, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    # Set when a member of the prescriber organization opens the orientation
    lue_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class BilanIntervention(models.Model):
    """Report filled by the offreur at the end of the follow-up, in the format of `companies.ProSupportReport`."""

    accompagnement = models.OneToOneField(Accompagnement, on_delete=models.CASCADE, related_name="bilan")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    # Same fields as ProSupportReport, so that its form and its display can be reused
    barriers = ArrayField(models.CharField(choices=ProSupportReportBarrier.choices), blank=True, default=list)
    other_barrier = models.TextField(blank=True, default="")
    autonomy = models.PositiveSmallIntegerField(choices=ProSupportReportAutonomy.choices)
    solution = models.CharField(choices=ProSupportReportSolution.choices, blank=True, default="")
    orientation = models.CharField(choices=ProSupportReportOrientation.choices, blank=True, default="")

    class Meta:
        verbose_name = "bilan de l’intervention"
        verbose_name_plural = "bilans de l’intervention"
        constraints = [
            models.CheckConstraint(
                name="%(class)s_autonomy_range",
                condition=Q(autonomy__range=(1, 5)),
                violation_error_message="L’autonomie est notée de 1 à 5.",
            ),
            models.CheckConstraint(
                name="%(class)s_solution_or_orientation",
                condition=Q(solution="", orientation__gt="") | Q(solution__gt="", orientation=""),
                violation_error_message="Un bilan comporte soit une solution envisagée, soit une orientation.",
            ),
        ]

    def get_barriers_display(self):
        return [ProSupportReportBarrier(barrier).label for barrier in self.barriers]
