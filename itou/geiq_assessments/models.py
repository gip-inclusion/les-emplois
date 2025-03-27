import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.files.models import File
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution


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
        if True:
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
