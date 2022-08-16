import functools

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Count, F
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

from itou.eligibility.models import AdministrativeCriteria
from itou.institutions.models import Institution
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siaes.models import Siae
from itou.users.enums import KIND_SIAE_STAFF
from itou.utils.emails import get_email_message


def select_min_max_job_applications(job_applications):
    # select SELECTION_PERCENTAGE % max, within bounds
    # minimum MIN job_applications, maximun MAX job_applications

    limit = int(
        job_applications.count()
        * evaluation_enums.EvaluationJobApplicationsBoundariesNumber.SELECTION_PERCENTAGE
        / 100
    )

    if limit < evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN:
        limit = evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN
    elif limit > evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX:
        limit = evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MAX

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
            evaluation_campaign.get_email_to_institution_ratio_to_select(ratio_selection_end_at)
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

    def eligible_siaes(self, upperbound=0):
        qs = (
            self.eligible_job_applications()
            .values("to_siae")
            .annotate(to_siae_count=Count("to_siae"))
            .filter(to_siae_count__gte=evaluation_enums.EvaluationJobApplicationsBoundariesNumber.MIN)
        )

        if upperbound != 0:
            qs = qs.filter(to_siae_count__lt=upperbound)

        return qs

    def number_of_siaes_to_select(self, upperbound=0):
        if self.eligible_siaes(upperbound=upperbound).count() > 0:
            return max(round(self.eligible_siaes(upperbound=upperbound).count() * self.chosen_percent / 100), 1)
        return 0

    def eligible_siaes_under_ratio(self, upperbound=0):
        return (
            self.eligible_siaes(upperbound=upperbound)
            .values_list("to_siae", flat=True)
            .order_by("?")[: self.number_of_siaes_to_select(upperbound=upperbound)]
        )

    def populate(
        self,
        set_at,
        upperbound=0,
    ):
        if self.evaluations_asked_at:
            raise CampaignAlreadyPopulatedException()

        with transaction.atomic():
            if not self.percent_set_at:
                self.percent_set_at = set_at
            self.evaluations_asked_at = set_at

            self.save(update_fields=["percent_set_at", "evaluations_asked_at"])

            evaluated_siaes = EvaluatedSiae.objects.bulk_create(
                EvaluatedSiae(evaluation_campaign=self, siae=Siae.objects.get(pk=pk))
                for pk in self.eligible_siaes_under_ratio(upperbound=upperbound)
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

            connection = mail.get_connection()
            emails = [evaluated_siae.get_email_to_siae_selected() for evaluated_siae in evaluated_siaes]
            emails += [self.get_email_to_institution_selected_siae()]
            connection.send_messages(emails)

    def transition_to_adversarial_phase(self):
        EvaluatedSiae.objects.filter(evaluation_campaign=self, reviewed_at__isnull=True).update(
            reviewed_at=timezone.now()
        )

    def close(self):
        if not self.ended_at:
            self.ended_at = timezone.now()
            self.save(update_fields=["ended_at"])

    # fixme vincentporte : to refactor. move all get_email_to_institution_xxx() method
    # to emails.py in institution model
    def get_email_to_institution_ratio_to_select(self, ratio_selection_end_at):
        to = self.institution.active_members
        context = {
            "ratio_selection_end_at": ratio_selection_end_at,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        }
        subject = "siae_evaluations/email/to_institution_ratio_to_select_subject.txt"
        body = "siae_evaluations/email/to_institution_ratio_to_select_body.txt"
        return get_email_message(to, context, subject, body)

    def get_email_to_institution_selected_siae(self):
        to = self.institution.active_members
        context = {
            # end_date for eligible siaes to return their documents of proofs is 6 weeks after notification
            "end_date": self.evaluations_asked_at + relativedelta(weeks=6),
            "evaluated_period_start_at": self.evaluated_period_start_at,
            "evaluated_period_end_at": self.evaluated_period_end_at,
        }
        subject = "siae_evaluations/email/to_institution_selected_siae_subject.txt"
        body = "siae_evaluations/email/to_institution_selected_siae_body.txt"
        return get_email_message(to, context, subject, body)


class EvaluatedSiaeQuerySet(models.QuerySet):
    def for_siae(self, siae):
        return self.filter(siae=siae)

    def in_progress(self):
        return self.exclude(evaluation_campaign__evaluations_asked_at=None).filter(evaluation_campaign__ended_at=None)


class EvaluatedSiaeManager(models.Manager):
    pass


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
    reviewed_at = models.DateTimeField(verbose_name=("Contrôlée le"), blank=True, null=True)

    objects = EvaluatedSiaeManager.from_queryset(EvaluatedSiaeQuerySet)()

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"
        unique_together = ("evaluation_campaign", "siae")

    def __str__(self):
        return f"{self.siae}"

    def review(self):
        if self.state in [evaluation_enums.EvaluatedSiaeState.ACCEPTED, evaluation_enums.EvaluatedSiaeState.REFUSED]:
            with transaction.atomic():

                email = {
                    (evaluation_enums.EvaluatedSiaeState.ACCEPTED, True): functools.partial(
                        self.get_email_to_siae_reviewed, adversarial=True
                    ),
                    (evaluation_enums.EvaluatedSiaeState.ACCEPTED, False): functools.partial(
                        self.get_email_to_siae_reviewed, adversarial=False
                    ),
                    (evaluation_enums.EvaluatedSiaeState.REFUSED, True): self.get_email_to_siae_adversarial_stage,
                    (evaluation_enums.EvaluatedSiaeState.REFUSED, False): self.get_email_to_siae_refused,
                }[(self.state, bool(self.reviewed_at))]()

                connection = mail.get_connection()
                connection.send_messages([email])

                self.reviewed_at = timezone.now()
                self.save(update_fields=["reviewed_at"])

    # fixme vincentporte : to refactor. move all get_email_to_siae_xxx() method to emails.py in siae model
    def get_email_to_siae_selected(self):
        to = self.siae.active_admin_members
        context = {
            "campaign": self.evaluation_campaign,
            "siae": self.siae,
            # end_date for eligible siaes to return their documents of proofs is 6 weeks after notification
            "end_date": timezone.now() + relativedelta(weeks=6),
            "url": (
                f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}"
                f"{reverse('siae_evaluations_views:siae_job_applications_list')}"
            ),
        }
        subject = "siae_evaluations/email/to_siae_selected_subject.txt"
        body = "siae_evaluations/email/to_siae_selected_body.txt"
        return get_email_message(to, context, subject, body)

    def get_email_to_siae_reviewed(self, adversarial=False):
        to = self.siae.active_admin_members
        context = {"evaluation_campaign": self.evaluation_campaign, "siae": self.siae, "adversarial": adversarial}
        subject = "siae_evaluations/email/to_siae_reviewed_subject.txt"
        body = "siae_evaluations/email/to_siae_reviewed_body.txt"
        return get_email_message(to, context, subject, body)

    def get_email_to_siae_refused(self):
        to = self.siae.active_admin_members
        context = {
            "evaluation_campaign": self.evaluation_campaign,
            "siae": self.siae,
        }
        subject = "siae_evaluations/email/to_siae_refused_subject.txt"
        body = "siae_evaluations/email/to_siae_refused_body.txt"
        return get_email_message(to, context, subject, body)

    def get_email_to_siae_adversarial_stage(self):
        to = self.siae.active_admin_members
        context = {
            "evaluation_campaign": self.evaluation_campaign,
            "siae": self.siae,
        }
        subject = "siae_evaluations/email/to_siae_adversarial_stage_subject.txt"
        body = "siae_evaluations/email/to_siae_adversarial_stage_body.txt"
        return get_email_message(to, context, subject, body)

    # fixme vincentporte : to refactor. move all get_email_to_institution_xxx() method
    # to emails.py in institution model
    def get_email_to_institution_submitted_by_siae(self):
        to = self.evaluation_campaign.institution.active_members
        context = {
            "siae": self.siae,
            "dashboard_url": f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{reverse('dashboard:index')}",
        }
        subject = "siae_evaluations/email/to_institution_submitted_by_siae_subject.txt"
        body = "siae_evaluations/email/to_institution_submitted_by_siae_body.txt"
        return get_email_message(to, context, subject, body)

    # fixme vincentporte : rsebille suggests to replace cached_property with prefetch_related
    @cached_property
    def state(self):

        # assuming the EvaluatedSiae instance is fully hydrated with its evaluated_job_applications
        # and evaluated_administrative_criteria before being called,
        # to prevent tons of additionnal queries in db.

        if (
            # edge case, evaluated_siae has no evaluated_job_application
            len(self.evaluated_job_applications.all()) == 0
            # at least one evaluated_job_application has no evaluated_administrative_criteria
            or any(
                len(evaluated_job_application.evaluated_administrative_criteria.all()) == 0
                for evaluated_job_application in self.evaluated_job_applications.all()
            )
            # at least one evaluated_administrative_criteria proof is not uploaded
            or any(
                eval_admin_crit.proof_url == ""
                for eval_job_app in self.evaluated_job_applications.all()
                for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
            )
        ):
            return evaluation_enums.EvaluatedSiaeState.PENDING

        if any(
            eval_admin_crit.submitted_at is None
            for eval_job_app in self.evaluated_job_applications.all()
            for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedSiaeState.SUBMITTABLE

        # PENDING and reviewed_at is none !!
        # OR PENDING with uploaded_at > reviewed_at
        if any(
            eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
            and (not self.reviewed_at or (eval_admin_crit.submitted_at > self.reviewed_at))
            for eval_job_app in self.evaluated_job_applications.all()
            for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedSiaeState.SUBMITTED

        if any(
            eval_admin_crit.review_state
            in [
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
            ]
            for eval_job_app in self.evaluated_job_applications.all()
            for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
        ):
            if self.reviewed_at and all(
                eval_admin_crit.submitted_at < self.reviewed_at
                for eval_job_app in self.evaluated_job_applications.all()
                for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
            ):
                return evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
            else:
                return evaluation_enums.EvaluatedSiaeState.REFUSED

        if self.reviewed_at and all(
            eval_admin_crit.submitted_at < self.reviewed_at
            for eval_job_app in self.evaluated_job_applications.all()
            for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedSiaeState.REVIEWED
        else:
            return evaluation_enums.EvaluatedSiaeState.ACCEPTED


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

    # fixme vincentporte : rsebille suggests to replace cached_property with prefetch_related
    @cached_property
    def state(self):

        # assuming the EvaluatedJobApplication instance is fully hydrated
        # with its evaluated_administrative_criteria before being called,
        # to prevent tons of additionnal queries in db.
        if len(self.evaluated_administrative_criteria.all()) == 0:
            return evaluation_enums.EvaluatedJobApplicationsState.PENDING

        if any(eval_admin_crit.proof_url == "" for eval_admin_crit in self.evaluated_administrative_criteria.all()):
            return evaluation_enums.EvaluatedJobApplicationsState.PROCESSING

        if any(
            eval_admin_crit.submitted_at is None for eval_admin_crit in self.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedJobApplicationsState.UPLOADED

        if any(
            eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
            for eval_admin_crit in self.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED

        if any(
            eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
            for eval_admin_crit in self.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2

        if any(
            eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
            for eval_admin_crit in self.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedJobApplicationsState.REFUSED

        if all(
            eval_admin_crit.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
            for eval_admin_crit in self.evaluated_administrative_criteria.all()
        ):
            return evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED

    @cached_property
    def should_select_criteria(self):
        if self.state == evaluation_enums.EvaluatedJobApplicationsState.PENDING:
            return evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING

        if self.evaluated_siae.reviewed_at:
            return evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE

        if self.state in [
            evaluation_enums.EvaluatedJobApplicationsState.PROCESSING,
            evaluation_enums.EvaluatedJobApplicationsState.UPLOADED,
        ]:
            return evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.EDITABLE

        return evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.NOTEDITABLE

    def save_selected_criteria(self, cleaned_keys, changed_keys):
        # cleaned_keys are checked fields when form is submitted.
        #    It contains new AND prexistant choices.
        # changed_keys are fields which status has changed when form is submitted :
        #    from unchecked to checked
        #    from checked to unchecked
        #    It contains new AND removed choices.

        with transaction.atomic():

            EvaluatedAdministrativeCriteria.objects.filter(
                pk__in=(
                    eval_criterion.pk
                    for eval_criterion in self.evaluated_administrative_criteria.all()
                    if eval_criterion.administrative_criteria.key in set(changed_keys) - set(cleaned_keys)
                )
            ).delete()

            EvaluatedAdministrativeCriteria.objects.bulk_create(
                [
                    EvaluatedAdministrativeCriteria(evaluated_job_application=self, administrative_criteria=criterion)
                    for criterion in AdministrativeCriteria.objects.all()
                    if criterion.key in set(changed_keys).intersection(cleaned_keys)
                ]
            )


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
    submitted_at = models.DateTimeField(verbose_name=("Transmis le"), blank=True, null=True)
    review_state = models.CharField(
        verbose_name="Vérification",
        max_length=10,
        choices=evaluation_enums.EvaluatedAdministrativeCriteriaState.choices,
        default=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
    )

    class Meta:
        verbose_name = "Critère administratif"
        verbose_name_plural = "Critères administratifs"
        unique_together = ("administrative_criteria", "evaluated_job_application")
        ordering = ["evaluated_job_application", "administrative_criteria"]

    def __str__(self):
        return f"{self.evaluated_job_application} - {self.administrative_criteria}"

    def can_upload(self):
        if self.submitted_at is None:
            return True

        return (
            self.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
            and self.evaluated_job_application.evaluated_siae.reviewed_at
        )
