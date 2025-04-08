import uuid

from django.conf import settings
from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.files.models import File
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.users.enums import Title
from itou.utils.templatetags.str_filters import pluralizefr


class AssessmentCampaign(models.Model):
    year = models.IntegerField(verbose_name="année", unique=True)
    submission_deadline = models.DateField(verbose_name="date limite de transmission du bilan d’exécution")
    review_deadline = models.DateField(verbose_name="date limite de contrôle du bilan d’exécution")

    class Meta:
        verbose_name = "campagne de bilan d’exécution"
        verbose_name_plural = "campagnes de bilan d’exécution"
        constraints = [
            models.CheckConstraint(
                name="geiq_review_after_submission",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle antérieure à la date de transmission"
                ),
                condition=(models.Q(review_deadline__gte=models.F("submission_deadline"))),
            ),
        ]

    def __str__(self):
        return f"Campagne des bilans d’exécution GEIQ de {self.year}"


class LabelInfos(models.Model):
    campaign = models.OneToOneField(AssessmentCampaign, on_delete=models.CASCADE, related_name="label_infos")
    data = models.JSONField(verbose_name="données label")
    synced_at = models.DateTimeField(verbose_name="données label récupérées le", auto_now=True)

    class Meta:
        verbose_name = "liste des GEIQ récupérée de label"
        verbose_name_plural = "listes des GEIQ récupérées de label"

    def __str__(self):
        return f"Liste récupérée le {timezone.localdate(self.synced_at).isoformat()}"


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    campaign = models.ForeignKey(AssessmentCampaign, related_name="assessments", on_delete=models.PROTECT)
    companies = models.ManyToManyField(
        Company,
        verbose_name="entreprises",
        related_name="assessments",
        limit_choices_to={"kind": CompanyKind.GEIQ},
    )
    institutions = models.ManyToManyField(
        Institution,
        verbose_name="institutions",
        related_name="implementation_assessments",
        through="AssessmentInstitutionLink",
        through_fields=("assessment", "institution"),
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
    )
    name_for_geiq = models.CharField(verbose_name="nom du bilan pour les GEIQ")
    name_for_institution = models.CharField(verbose_name="nom du bilan pour les institutions")
    label_geiq_id = models.IntegerField(verbose_name="identifiant label du GEIQ principal")
    label_antennas = models.JSONField(verbose_name="antennes label concernées par le bilan")

    summary_document_file = models.OneToOneField(
        File,
        verbose_name="document de synthèse généré par label",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    structure_financial_assessment_file = models.OneToOneField(
        File,
        verbose_name="bilan financier de la structure",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    action_financial_assessment_file = models.OneToOneField(
        File,
        verbose_name="bilan financier de l’action",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    label_rates = models.JSONField(verbose_name="taux récupérés sur l'API label", null=True)
    employee_nb = models.PositiveSmallIntegerField("nombre d'employés", default=0)
    contracts_synced_at = models.DateTimeField("données de contrats label récupérées le", blank=True, null=True)
    # GEIQ actions
    contracts_selection_validated_at = models.DateTimeField("sélection des contrats validée le", blank=True, null=True)
    geiq_comment = models.TextField("commentaire général du GEIQ", blank=True)

    submitted_at = models.DateTimeField("transmis le", blank=True, null=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="transmis par",
        related_name="submitted_assessments",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    # Institution actions
    decision_validated_at = models.DateTimeField("décision saisie le", blank=True, null=True)
    grants_selection_validated_at = models.DateTimeField("aides accordées validées le", blank=True, null=True)
    reviewed_at = models.DateTimeField("contrôlé le", blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="contrôlé par",
        related_name="reviewed_assessments",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )

    class Meta:
        verbose_name = "bilan d’exécution"
        verbose_name_plural = "bilans d’exécution"

    def action_financial_assessment_filename(self):
        return f"Bilan financier action {self.campaign.year}.pdf"

    def structure_financial_assessment_filename(self):
        return f"Bilan financier structure {self.campaign.year}.pdf"

    def summary_document_filename(self):
        return f"Synthèse {self.campaign.year}.pdf"

    def missing_actions_to_submit(self):
        actions = []
        if not self.summary_document_file:
            actions.append("Récupérer le document de synthèse de label")
        if not self.structure_financial_assessment_file:
            actions.append("Récupérer le bilan financier de la structure de label")
        if not self.action_financial_assessment_file:
            actions.append("Transmettre le bilan financier de l’action")
        if not self.contracts_selection_validated_at:
            actions.append("Détail et sélection des contrats à présenter")
        if not self.geiq_comment:
            actions.append("Commentaire")
        return actions

    def missing_actions_to_review(self):
        actions = []
        if not self.grants_selection_validated_at:
            actions.append("Contrôler la sélection")
        if not self.decision_validated_at:
            actions.append("Saisir la décision")
        return actions

    def get_allowance_stats(self):
        return (
            EmployeeContract.objects.filter(employee__assessment=self)
            .filter(allowance_requested=True)
            .aggregate(
                contracts_nb=Count("pk"),
                aid_of_0_nb=Count("pk", filter=Q(employee__allowance_amount=0)),
                aid_of_814_nb=Count("pk", filter=Q(employee__allowance_amount=814)),
                aid_of_1400_nb=Count("pk", filter=Q(employee__allowance_amount=1400)),
                potential_aid_amount=Sum("employee__allowance_amount"),
            )
        )

    def label_antenna_ids(self):
        if not self.label_antennas:
            return []
        return [antenna["id"] for antenna in self.label_antennas]


class AssessmentInstitutionLink(models.Model):
    assessment = models.ForeignKey(
        Assessment, verbose_name="bilan lié", related_name="institution_links", on_delete=models.CASCADE
    )
    institution = models.ForeignKey(
        Institution,
        verbose_name="institution liée",
        related_name="assessment_links",
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
        on_delete=models.PROTECT,
    )
    with_convention = models.BooleanField(verbose_name="avec un convention", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assessment", "institution"], name="assessment_institution_unique"),
        ]


class Employee(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="employees")
    label_id = models.IntegerField(verbose_name="ID label")
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
    allowance_amount = models.IntegerField(verbose_name="aide potentielle")

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

    def get_prior_actions(self):
        actions = []
        # Sorted in python to leverage prefetch_related field
        for prequalification in sorted(self.prequalifications.all(), key=lambda prequal: prequal.end_at, reverse=True):
            if prequalification.other_data.get("action_pre_qualification", {}).get("libelle_abr") != "AUTRE":
                action = prequalification.other_data.get("action_pre_qualification", {}).get("libelle")
            elif other_action := prequalification.other_data.get("autre_type_prequalification_action"):
                action = other_action
            else:
                action = "Autre"
            hour_nb = prequalification.other_data.get("nombre_heure_formation", 0)
            actions.append(
                f"{action} ({hour_nb} heure{pluralizefr(hour_nb)} "
                f"du {prequalification.start_at:%d/%m/%Y} au {prequalification.end_at:%d/%m/%Y})"
            )
        return actions


class EmployeeContract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")

    start_at = models.DateField(verbose_name="date de début")
    planned_end_at = models.DateField(verbose_name="date de fin prévisionnelle")
    end_at = models.DateField(verbose_name="date de fin", null=True)

    allowance_requested = models.BooleanField(verbose_name="aide demandée par le GEIQ")
    allowance_granted = models.BooleanField(verbose_name="aide acceptée par l'institution")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "contrat"
        constraints = [
            models.CheckConstraint(
                name="geiq_allowance_requested_or_not_granted",
                violation_error_message=("Impossible d'accorder une aide non-sollicitée"),
                condition=(models.Q(allowance_requested=True) | models.Q(allowance_granted=False)),
            ),
        ]

    def with_3_months_in_assessment_year(self):
        from itou.geiq.sync import _more_than_3_months_in_year

        return _more_than_3_months_in_year(
            self.start_at, self.end_at or self.planned_end_at, year=self.employee.assessment.campaign.year
        )


class EmployeePrequalification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="prequalifications")

    start_at = models.DateField(verbose_name="date de début")
    end_at = models.DateField(verbose_name="date de fin")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "préqualification"
