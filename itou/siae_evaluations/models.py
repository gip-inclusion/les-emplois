from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from itou.institutions.models import Institution
from itou.siae_evaluations import enums as evaluation_enums
from itou.utils.emails import get_email_message, sanitize_mailjet_recipients_list


def validate_institution(institution_id):
    try:
        institution = Institution.objects.get(pk=institution_id)
    except Institution.DoesNotExist:
        raise ValidationError("L'institution sélectionnée n'existe pas.")

    if institution.kind != Institution.Kind.DDETS:
        raise ValidationError(f"Sélectionnez une institution de type {Institution.Kind.DDETS}")


def email_campaign_is_setup(emails, ratio_selection_end_at):

    return get_email_message(
        to=[settings.DEFAULT_FROM_EMAIL],
        context={
            "ratio_selection_end_at": ratio_selection_end_at,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        },
        subject="siae_evaluations/email/campaign_is_setup_subject.txt",
        body="siae_evaluations/email/campaign_is_setup_body.txt",
        bcc=emails,
    )


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

    if evaluation_campaign_list:

        for chunk_emails in sanitize_mailjet_recipients_list(
            institutions.prefetch_active_memberships().values_list("members__email", flat=True).distinct(), 2
        ):
            email_campaign_is_setup(chunk_emails, ratio_selection_end_at).send()

    return len(evaluation_campaign_list)


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
