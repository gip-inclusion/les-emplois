from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Count, F
from django.urls import reverse
from django.utils import timezone

from itou.institutions.models import Institution
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siaes.models import Siae
from itou.utils.emails import get_email_message
from itou.utils.perms.user import KIND_SIAE_STAFF


def select_min_max_job_applications(job_applications):
    # select 20% max, within bounds
    # minimum 10 job_applications, maximun 20 job_applications

    count = job_applications.count()
    limit = int(round(count * evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTION_PERCENTAGE / 100))

    if count < evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN:
        limit = 0
    elif count > evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX:
        limit = evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTED_MAX
    return job_applications.order_by("?")[:limit]


def validate_institution(institution_id):
    try:
        institution = Institution.objects.get(pk=institution_id)
    except Institution.DoesNotExist as exception:
        raise ValidationError("L'institution sélectionnée n'existe pas.") from exception

    if institution.kind != Institution.Kind.DDETS:
        raise ValidationError(f"Sélectionnez une institution de type {Institution.Kind.DDETS}")


def create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at):
    """
    Create a campaign for each institution whose kind is DDETS.
    This method is intented to be executed manually, until it will be automised.
    """

    name = (
        f"contrôle pour la période du {evaluated_period_start_at.strftime('%d/%m/%Y')} "
        f"au {evaluated_period_end_at.strftime('%d/%m/%Y')}"
    )

    institutions = Institution.objects.filter(kind=Institution.Kind.DDETS)

    evaluation_campaign_list = EvaluationCampaign.objects.bulk_create(
        EvaluationCampaign(
            name=name,
            evaluated_period_start_at=evaluated_period_start_at,
            evaluated_period_end_at=evaluated_period_end_at,
            institution=institution,
        )
        for institution in institutions
    )

    # Send notification.
    if evaluation_campaign_list:
        connection = mail.get_connection()
        emails = [
            evaluation_campaign.get_email_institution_notification(ratio_selection_end_at)
            for evaluation_campaign in evaluation_campaign_list
        ]
        connection.send_messages(emails)

    return len(evaluation_campaign_list)


class CampaignAlreadyPopulatedException(Exception):
    pass


class EvaluationCampaignQuerySet(models.QuerySet):
    def for_institution(self, institution):
        return self.filter(institution=institution).order_by("-evaluated_period_end_at")

    def in_progress(self):
        return self.filter(ended_at=None)


class EvaluationCampaignManager(models.Manager):
    def has_active_campaign(self, institution):
        return self.for_institution(institution).in_progress().exists()

    def first_active_campaign(self, institution):
        return self.for_institution(institution).in_progress().first()


class EvaluationCampaign(models.Model):
    """
    A campaign of evaluation
    - is run by one institution which kind is DDETS,
    - According to a control agenda (ie : from 01.04.2022 to 30.06.2022)
    - on self-approvals made by siaes in the department of the institution (ie : departement 14),
    - during the evaluated period (ie : from 01.01.2021 to 31.12.2021).
    """

    name = models.CharField(verbose_name="Nom de la campagne d'évaluation", max_length=100, blank=False, null=False)

    # dates of execution of the campaign
    created_at = models.DateTimeField(verbose_name=("Date de création"), default=timezone.now)
    percent_set_at = models.DateTimeField(verbose_name=("Date de paramétrage de la sélection"), blank=True, null=True)
    evaluations_asked_at = models.DateTimeField(
        verbose_name=("Date de notification du contrôle aux Siaes"), blank=True, null=True
    )
    ended_at = models.DateTimeField(verbose_name=("Date de clôture de la campagne"), blank=True, null=True)

    # dates of the evaluated period
    # to do later : add coherence controls between campaign.
    # Campaign B for one institution cannot start before the end of campaign A of the same institution
    evaluated_period_start_at = models.DateField(
        verbose_name=("Date de début de la période contrôlée"), blank=False, null=False
    )
    evaluated_period_end_at = models.DateField(
        verbose_name=("Date de fin de la période contrôlée"), blank=False, null=False
    )

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.CASCADE,
        related_name="evaluation_campaigns",
        verbose_name=("DDETS responsable du contrôle"),
        validators=[validate_institution],
    )

    chosen_percent = models.PositiveIntegerField(
        verbose_name="Pourcentage de sélection",
        default=evaluation_enums.EvaluationChosenPercent.DEFAULT,
        validators=[
            MinValueValidator(evaluation_enums.EvaluationChosenPercent.MIN),
            MaxValueValidator(evaluation_enums.EvaluationChosenPercent.MAX),
        ],
    )

    objects = EvaluationCampaignManager.from_queryset(EvaluationCampaignQuerySet)()

    class Meta:
        verbose_name = "Campagne"
        verbose_name_plural = "Campagnes"
        ordering = ["-name", "institution__name"]

    def __str__(self):
        return f"{self.institution.name} - {self.name}"

    def clean(self):
        if self.evaluated_period_end_at <= self.evaluated_period_start_at:
            raise ValidationError("La date de début de la période contrôlée doit être antérieure à sa date de fin.")

    def eligible_job_applications(self):
        # accepted job_applications with self-approval made by hiring siae.
        return (
            JobApplication.objects.exclude(approval=None)
            .select_related("approval", "to_siae", "eligibility_diagnosis", "eligibility_diagnosis__author_siae")
            .filter(
                to_siae__department=self.institution.department,
                to_siae__kind__in=evaluation_enums.EvaluationSiaesKind.Evaluable,
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                eligibility_diagnosis__author_kind=KIND_SIAE_STAFF,
                eligibility_diagnosis__author_siae=F("to_siae"),
                hiring_start_at__gte=self.evaluated_period_start_at,
                hiring_start_at__lte=self.evaluated_period_end_at,
            )
        )

    def eligible_siaes(self):
        return (
            self.eligible_job_applications()
            .values("to_siae")
            .annotate(to_siae_count=Count("to_siae"))
            .filter(to_siae_count__gte=evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN)
        )

    def number_of_siaes_to_select(self):
        if self.eligible_siaes().count() > 0:
            return max(round(self.eligible_siaes().count() * self.chosen_percent / 100), 1)
        return 0

    def eligible_siaes_under_ratio(self):
        return (
            self.eligible_siaes().values_list("to_siae", flat=True).order_by("?")[: self.number_of_siaes_to_select()]
        )

    def populate(self, set_at):
        if self.evaluations_asked_at:
            raise CampaignAlreadyPopulatedException()

        with transaction.atomic():
            if not self.percent_set_at:
                self.percent_set_at = set_at
            self.evaluations_asked_at = set_at

            self.save(update_fields=["percent_set_at", "evaluations_asked_at"])

            evaluated_siaes = EvaluatedSiae.objects.bulk_create(
                EvaluatedSiae(evaluation_campaign=self, siae=Siae.objects.get(pk=pk))
                for pk in self.eligible_siaes_under_ratio()
            )

            EvaluatedJobApplication.objects.bulk_create(
                [
                    EvaluatedJobApplication(evaluated_siae=evaluated_siae, job_application=job_application)
                    for evaluated_siae in evaluated_siaes
                    for job_application in select_min_max_job_applications(
                        self.eligible_job_applications().filter(to_siae=evaluated_siae.siae)
                    )
                ]
            )

    def get_email_institution_notification(self, ratio_selection_end_at):
        to = self.institution.active_members
        context = {
            "ratio_selection_end_at": ratio_selection_end_at,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        }
        subject = "siae_evaluations/email/email_institution_notification_subject.txt"
        body = "siae_evaluations/email/email_institution_notification_body.txt"
        return get_email_message(to, context, subject, body)


class EvaluatedSiaeQuerySet(models.QuerySet):
    def for_siae(self, siae):
        return self.filter(siae=siae)

    def in_progress(self):
        return self.exclude(evaluation_campaign__evaluations_asked_at=None).filter(evaluation_campaign__ended_at=None)


class EvaluatedSiaeManager(models.Manager):
    def has_active_campaign(self, siae):
        return self.for_siae(siae).in_progress().exists()


class EvaluatedSiae(models.Model):

    evaluation_campaign = models.ForeignKey(
        EvaluationCampaign,
        verbose_name="Contrôle",
        on_delete=models.CASCADE,
        related_name="evaluated_siaes",
    )
    siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name="SIAE",
        on_delete=models.CASCADE,
        related_name="evaluated_siaes",
    )

    objects = EvaluatedSiaeManager.from_queryset(EvaluatedSiaeQuerySet)()

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"
        unique_together = ("evaluation_campaign", "siae")

    def __str__(self):
        return f"{self.siae}"


class EvaluatedJobApplication(models.Model):

    job_application = models.ForeignKey(
        "job_applications.JobApplication",
        verbose_name="Candidature",
        on_delete=models.CASCADE,
        related_name="evaluated_job_applications",
    )

    evaluated_siae = models.ForeignKey(
        EvaluatedSiae,
        verbose_name="SIAE évaluée",
        on_delete=models.CASCADE,
        related_name="evaluated_job_applications",
    )
    labor_inspector_explanation = models.TextField(verbose_name="Commentaires de l'inspecteur du travail", blank=True)

    class Meta:
        verbose_name = "Auto-prescription"
        verbose_name_plural = "Auto-prescriptions"

    def __str__(self):
        return f"{self.job_application}"

    @property
    def state(self):
        # property in progress, new conditionnal state will be added further
        return evaluation_enums.EvaluationJobApplicationsState.PENDING


class EvaluatedAdministrativeCriteria(models.Model):

    administrative_criteria = models.ForeignKey(
        "eligibility.AdministrativeCriteria",
        verbose_name="Critère administratif",
        on_delete=models.CASCADE,
        related_name="evaluated_administrative_criteria",
    )

    evaluated_job_application = models.ForeignKey(
        EvaluatedJobApplication,
        verbose_name="Candidature évaluée",
        on_delete=models.CASCADE,
        related_name="evaluated_administrative_criteria",
    )

    proof_url = models.URLField(max_length=500, verbose_name="Lien vers le justificatif", blank=True)
    uploaded_at = models.DateTimeField(verbose_name=("Téléversé le"), blank=True, null=True)

    class Meta:
        verbose_name = "Critère administratif"
        verbose_name_plural = "Critères administratifs"

    def __str__(self):
        return f"{self.evaluated_job_application} - {self.administrative_criteria}"
