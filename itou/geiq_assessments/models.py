import datetime
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.files.models import File
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.users.enums import Title


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
    contracts_synced_at = models.DateTimeField("données de contrats label récupérées le", blank=True, null=True)
    contracts_selection_validated_at = models.DateTimeField(
        "données de contrats label récupérées le", blank=True, null=True
    )
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
        if not self.submitted_at:
            actions.append("Envoi du bilan d’exécution")
        return actions


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


class EmployeeContract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")

    start_at = models.DateField(verbose_name="date de début")
    planned_end_at = models.DateField(verbose_name="date de fin prévisionnelle")
    end_at = models.DateField(verbose_name="date de fin", null=True)

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "contrat"

    def with_3_months_in_assessment_year(self):
        assessment_year = self.employee.assessment.campaign.year
        if self.start_at.year < assessment_year:
            start = datetime.date(assessment_year, 1, 1)
        elif self.start_at.year > assessment_year:
            # This shouldn't happen
            return False
        else:
            start = self.start_at
        end = self.end_at or self.planned_end_at
        if end.year < assessment_year:
            return False
        elif end.year > assessment_year:
            end = datetime.date(assessment_year, 12, 31)
        return start - datetime.timedelta(days=1) + relativedelta(months=3) <= end


class EmployeePrequalification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="prequalifications")

    start_at = models.DateField(verbose_name="date de début")
    end_at = models.DateField(verbose_name="date de fin")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "préqualification"
