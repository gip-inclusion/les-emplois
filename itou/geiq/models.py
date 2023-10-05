from django.conf import settings
from django.db import models

from itou.companies.models import Company
from itou.files.models import File
from itou.institutions.models import Institution
from itou.users.enums import Title

from .enums import ReviewState


class ImplementationAssessmentCampaign(models.Model):
    year = models.IntegerField(verbose_name="année", unique=True)
    submission_deadline = models.DateField(verbose_name="date limite de transmission du bilan d’exécution")
    review_deadline = models.DateField(verbose_name="date limite de contrôle du bilan d’exécution")

    class Meta:
        verbose_name = "campagne de bilan d’exécution"
        verbose_name_plural = "campagnes de bilan d’exécution"
        constraints = [
            models.CheckConstraint(
                name="review_after_submission",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle antérieure à la date de transmission"
                ),
                check=(models.Q(review_deadline__gte=models.F("submission_deadline"))),
            ),
        ]

    def __str__(self):
        return f"Campagne des bilans d’exécution GEIQ de {self.year}"


class ImplementationAssessment(models.Model):
    campaign = models.ForeignKey(
        ImplementationAssessmentCampaign, related_name="implementation_assessments", on_delete=models.PROTECT
    )
    label_id = models.IntegerField(verbose_name="ID LABEL")
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="implementation_assessments"
    )  # Match based on SIRET
    last_synced_at = models.DateTimeField(verbose_name="dernière synchronisation à", blank=True, null=True)

    other_data = models.JSONField(verbose_name="autres données")

    activity_report_file = models.OneToOneField(
        File,
        verbose_name="document de synthèse",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    submitted_at = models.DateTimeField("transmis le", blank=True, null=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="transmis par",
        related_name="submitted_geiq_assessment_set",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )

    reviewed_at = models.DateTimeField("date de contrôle", blank=True, null=True)
    review_state = models.CharField(
        verbose_name="résultat du contrôle",
        blank=True,
        null=True,
        choices=ReviewState.choices,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="contrôlé par",
        related_name="reviewed_geiq_assessment_set",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    review_institution = models.ForeignKey(
        Institution,
        verbose_name="institution responsable du contrôle",
        related_name="reviewed_geiq_assessment_set",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    review_comment = models.TextField("commentaire", blank=True)

    class Meta:
        verbose_name = "bilan d’exécution"
        verbose_name_plural = "bilans d’exécution"
        unique_together = [
            ("campaign", "label_id"),
            ("campaign", "company"),
        ]
        constraints = [
            models.CheckConstraint(
                name="full_submission_or_no_submission",
                violation_error_message="Impossible d'avoir un envoi partiel",
                check=(
                    models.Q(submitted_at__isnull=True)
                    | models.Q(
                        submitted_at__isnull=False, last_synced_at__isnull=False, activity_report_file__isnull=False
                    )
                ),
            ),
            models.CheckConstraint(
                name="reviewed_at_only_after_submitted_at",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle sans une date de soumission antérieure"
                ),
                check=(
                    models.Q(reviewed_at__isnull=True)
                    | models.Q(submitted_at__isnull=False, reviewed_at__gte=models.F("submitted_at"))
                ),
            ),
            models.CheckConstraint(
                name="full_review_or_no_review",
                violation_error_message="Impossible d'avoir un contrôle partiel",
                check=(
                    models.Q(
                        reviewed_at__isnull=True,
                        review_state__isnull=True,
                        review_institution__isnull=True,
                        review_comment="",
                    )
                    | (
                        models.Q(
                            reviewed_at__isnull=False, review_state__isnull=False, review_institution__isnull=False
                        )
                        & ~models.Q(review_comment="")
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"Bilan {self.campaign.year} pour {self.company.display_name}"


class Employee(models.Model):
    assessment = models.ForeignKey(ImplementationAssessment, on_delete=models.CASCADE, related_name="employees")
    label_id = models.IntegerField(verbose_name="ID LABEL")
    last_name = models.CharField(verbose_name="nom de famille")
    first_name = models.CharField(verbose_name="prénom")
    birthdate = models.DateField(verbose_name="date de naissance")
    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        default="",
        choices=Title.choices,
    )

    annex1_nb = models.IntegerField(verbose_name="nombre de critères d'éligibilité de l'annexe 1")
    annex2_level1_nb = models.IntegerField(verbose_name="nombre de critères d'éligibilité de l'annexe 2 niveau 1")
    annex2_level2_nb = models.IntegerField(verbose_name="nombre de critères d'éligibilité de l'annexe 2 niveau 2")
    allowance_amount = models.IntegerField(verbose_name="aide potentielle")

    support_days_nb = models.PositiveIntegerField(verbose_name="nombre de jours d’accompagnement")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "employé"
        unique_together = [
            ("assessment", "label_id"),
        ]

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = f"{self.first_name.strip().title()} {self.last_name.upper().strip()}"
        return full_name.strip()

    def __str__(self):
        return self.get_full_name()

    def display_prior_actions(self):
        actions = []
        # Sorted in python to leverage prefetch_related field
        for prequalification in sorted(self.prequalifications.all(), key=lambda prequal: prequal.end_at, reverse=True):
            years = {str(prequalification.start_at.year), str(prequalification.end_at.year)}
            display_years = "-".join(sorted(years))

            if prequalification.other_data.get("action_pre_qualification", {}).get("libelle_abr") != "AUTRE":
                action = prequalification.other_data.get("action_pre_qualification", {}).get("libelle")
            elif other_action := prequalification.other_data.get("autre_type_prequalification_action"):
                action = other_action
            else:
                action = "Autre"
            actions.append(f"{action} ({display_years})")
        return ", ".join(actions)


class EmployeeContract(models.Model):
    label_id = models.IntegerField(verbose_name="ID LABEL")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")

    start_at = models.DateField(verbose_name="date de début")
    planned_end_at = models.DateField(verbose_name="date de fin prévisionnelle")
    end_at = models.DateField(verbose_name="date de fin", null=True)

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "contrat"


class EmployeePrequalification(models.Model):
    label_id = models.IntegerField(verbose_name="ID LABEL")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="prequalifications")

    start_at = models.DateField(verbose_name="date de début")
    end_at = models.DateField(verbose_name="date de fin")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "préqualification"
