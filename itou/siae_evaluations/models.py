import functools

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone
from django.utils.functional import cached_property

from itou.eligibility.models import AdministrativeCriteria
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.emails import CampaignEmailFactory, SIAEEmailFactory
from itou.siaes.models import Siae
from itou.users.enums import KIND_SIAE_STAFF
from itou.utils.emails import send_email_messages
from itou.utils.models import InclusiveDateRangeField

from .constants import CAMPAIGN_VIEWABLE_DURATION


def select_min_max_job_applications(job_applications):
    # select SELECTION_PERCENTAGE % max, within bounds
    # minimum MIN job_applications, maximum MAX job_applications

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

    if institution.kind != InstitutionKind.DDETS:
        raise ValidationError(f"Sélectionnez une institution de type {InstitutionKind.DDETS}")


def create_campaigns(evaluated_period_start_at, evaluated_period_end_at, ratio_selection_end_at, institution_ids=None):
    """
    Create a campaign for each institution whose kind is DDETS (possibly limited by institution_ids).
    This method is intented to be executed manually, until it will be automised.
    """

    name = (
        f"contrôle pour la période du {evaluated_period_start_at.strftime('%d/%m/%Y')} "
        f"au {evaluated_period_end_at.strftime('%d/%m/%Y')}"
    )

    institutions = Institution.objects.filter(kind=InstitutionKind.DDETS)
    if institution_ids:
        institutions = institutions.filter(pk__in=institution_ids)

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
        send_email_messages(
            CampaignEmailFactory(evaluation_campaign).ratio_to_select(ratio_selection_end_at)
            for evaluation_campaign in evaluation_campaign_list
        )

    return len(evaluation_campaign_list)


class CampaignAlreadyPopulatedException(Exception):
    pass


class EvaluationCampaignQuerySet(models.QuerySet):
    in_progress_q = Q(ended_at=None)

    def for_institution(self, institution):
        return self.filter(institution=institution).order_by("-evaluated_period_end_at")

    def in_progress(self):
        return self.filter(self.in_progress_q)

    def viewable(self):
        recent_q = Q(ended_at__gte=timezone.now() - CAMPAIGN_VIEWABLE_DURATION)
        return self.filter(self.in_progress_q | recent_q)


class EvaluationCampaign(models.Model):
    """
    A campaign of evaluation
    - is run by one institution which kind is DDETS,
    - According to a control agenda (ie : from 01.04.2022 to 30.06.2022)
    - on self-approvals made by siaes in the department of the institution (ie : departement 14),
    - during the evaluated period (ie : from 01.01.2021 to 31.12.2021).
    """

    ADVERSARIAL_STAGE_START_DELTA = relativedelta(weeks=6)

    name = models.CharField(verbose_name="Nom de la campagne d'évaluation", max_length=100, blank=False, null=False)

    # dates of execution of the campaign
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    percent_set_at = models.DateTimeField(verbose_name="Date de paramétrage de la sélection", blank=True, null=True)
    evaluations_asked_at = models.DateTimeField(
        verbose_name="Date de notification du contrôle aux Siaes", blank=True, null=True
    )
    ended_at = models.DateTimeField(verbose_name="Date de clôture de la campagne", blank=True, null=True)

    # dates of the evaluated period
    # to do later : add coherence controls between campaign.
    # Campaign B for one institution cannot start before the end of campaign A of the same institution
    evaluated_period_start_at = models.DateField(
        verbose_name="Date de début de la période contrôlée", blank=False, null=False
    )
    evaluated_period_end_at = models.DateField(
        verbose_name="Date de fin de la période contrôlée", blank=False, null=False
    )

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.CASCADE,
        related_name="evaluation_campaigns",
        verbose_name="DDETS responsable du contrôle",
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

    objects = EvaluationCampaignQuerySet.as_manager()

    class Meta:
        verbose_name = "Campagne"
        verbose_name_plural = "Campagnes"
        ordering = ["-name", "institution__name"]

    def __str__(self):
        return f"{self.institution.name} - {self.name}"

    def clean(self):
        if self.evaluated_period_end_at <= self.evaluated_period_start_at:
            raise ValidationError("La date de début de la période contrôlée doit être antérieure à sa date de fin.")

    @property
    def adversarial_stage_start_date(self):
        return self.evaluations_asked_at.date() + EvaluationCampaign.ADVERSARIAL_STAGE_START_DELTA

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
                approval__number__startswith=settings.ASP_ITOU_PREFIX,
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
        eligible_count = self.eligible_siaes().count()
        if eligible_count:
            return max(round(eligible_count * self.chosen_percent / 100), 1)
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

            emails = [SIAEEmailFactory(evaluated_siae).selected() for evaluated_siae in evaluated_siaes]
            emails += [CampaignEmailFactory(self).selected_siae()]
            send_email_messages(emails)

    def transition_to_adversarial_phase(self):
        now = timezone.now()
        siaes_not_reviewed = (
            EvaluatedSiae.objects.filter(evaluation_campaign=self, reviewed_at__isnull=True)
            .select_related("evaluation_campaign__institution", "siae")
            .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
        )
        emails = []
        accept_by_default = []
        transition_to_adversarial_stage = []
        for evaluated_siae in siaes_not_reviewed:
            state = evaluated_siae.state
            if state in [
                evaluation_enums.EvaluatedSiaeState.PENDING,
                evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
            ]:
                evaluated_siae.reviewed_at = now
                transition_to_adversarial_stage.append(evaluated_siae)
                emails.append(SIAEEmailFactory(evaluated_siae).forced_to_adversarial_stage())
            elif state == evaluation_enums.EvaluatedSiaeState.SUBMITTED:
                evaluated_siae.reviewed_at = now
                evaluated_siae.final_reviewed_at = now
                accept_by_default.append(evaluated_siae)
                emails.append(SIAEEmailFactory(evaluated_siae).force_accepted())
        if transition_to_adversarial_stage or accept_by_default:
            transition_to_adversarial_stage.sort(key=lambda evaluated_siae: evaluated_siae.siae.name)
            accept_by_default.sort(key=lambda evaluated_siae: evaluated_siae.siae.name)
            summary_email = CampaignEmailFactory(self).transition_to_adversarial_stage(
                transition_to_adversarial_stage,
                accept_by_default,
            )
            emails.append(summary_email)
            send_email_messages(emails)
        EvaluatedSiae.objects.bulk_update(
            accept_by_default + transition_to_adversarial_stage,
            ["reviewed_at", "final_reviewed_at"],
        )

    def close(self):
        if not self.ended_at:
            self.ended_at = timezone.now()
            self.save(update_fields=["ended_at"])
            evaluated_siaes = (
                EvaluatedSiae.objects.filter(evaluation_campaign=self)
                .filter(notified_at=None)
                .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
            )
            has_siae_to_notify = False
            siae_without_proofs = []
            for evaluated_siae in evaluated_siaes:
                # Computing the state is costly, avoid it when possible.
                if not has_siae_to_notify:
                    has_siae_to_notify |= (
                        evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING
                    )
                if evaluated_siae.final_reviewed_at is None:
                    criterias = [
                        crit
                        for jobapp in evaluated_siae.evaluated_job_applications.all()
                        for crit in jobapp.evaluated_administrative_criteria.all()
                    ]
                    if len(criterias) == 0 or any(crit.submitted_at is None for crit in criterias):
                        siae_without_proofs.append(evaluated_siae)
                        has_siae_to_notify = True
            emails = [SIAEEmailFactory(evaluated_siae).refused_no_proofs() for evaluated_siae in siae_without_proofs]
            if has_siae_to_notify:
                emails.append(CampaignEmailFactory(self).close())
            send_email_messages(emails)


class EvaluatedSiaeQuerySet(models.QuerySet):
    def for_siae(self, siae):
        return self.filter(siae=siae)

    def in_progress(self):
        return self.exclude(evaluation_campaign__evaluations_asked_at=None).filter(
            evaluation_campaign__ended_at=None,
            final_reviewed_at=None,
        )

    def viewable(self):
        return self.filter(evaluation_campaign__in=EvaluationCampaign.objects.viewable())

    def did_not_send_proof(self):
        return self.exclude(
            Exists(
                EvaluatedAdministrativeCriteria.objects.filter(
                    evaluated_job_application__evaluated_siae=OuterRef("pk"),
                    submitted_at__isnull=False,
                )
            )
        )


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
    # In “phase amiable” until documents have been reviewed.
    reviewed_at = models.DateTimeField(verbose_name="Contrôlée le", blank=True, null=True)
    # Refused documents from the phase amiable can be uploaded again, a second
    # refusal is final (phase contradictoire).
    final_reviewed_at = models.DateTimeField(verbose_name="Contrôle définitif le", blank=True, null=True)

    # After a refused evaluation, the SIAE is notified of sanctions.
    notified_at = models.DateTimeField(verbose_name="notifiée le", blank=True, null=True)
    notification_reason = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=evaluation_enums.EvaluatedSiaeNotificationReason.choices,
        verbose_name="raison principale",
    )
    notification_text = models.TextField(blank=True, null=True, verbose_name="commentaire")

    reminder_sent_at = models.DateTimeField(verbose_name="rappel envoyé le", null=True, blank=True)

    objects = EvaluatedSiaeQuerySet.as_manager()

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"
        unique_together = ("evaluation_campaign", "siae")

    def __str__(self):
        return f"{self.siae}"

    @property
    def can_review(self):
        if self.reviewed_at is None:
            return self.state in {
                evaluation_enums.EvaluatedSiaeState.ACCEPTED,
                evaluation_enums.EvaluatedSiaeState.REFUSED,
            }
        if self.final_reviewed_at is None:
            return (
                self.state == evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
                and not EvaluatedAdministrativeCriteria.objects.filter(
                    evaluated_job_application__evaluated_siae_id=self.pk,
                    review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
                    submitted_at__lt=self.reviewed_at,
                ).exists()
            )
        return False

    def review(self):
        ACCEPTED = evaluation_enums.EvaluatedSiaeState.ACCEPTED
        REFUSED = evaluation_enums.EvaluatedSiaeState.REFUSED
        ADVERSARIAL_STAGE = evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
        NOTIFICATION_PENDING = evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING
        from_adversarial_stage = bool(self.reviewed_at)
        previous_state = self.state

        now = timezone.now()
        if previous_state == ACCEPTED:
            self.reviewed_at = now
            self.final_reviewed_at = now
        elif previous_state == REFUSED:
            self.reviewed_at = now
        elif previous_state == ADVERSARIAL_STAGE:
            self.final_reviewed_at = now
        else:
            raise TypeError(f"Cannot review an “{self.__class__.__name__}” with status “{self.state}”.")
        self.save()
        # Invalidate the cache, a review changes the state of the evaluation.
        del self.state
        email = {
            (ACCEPTED, True): functools.partial(SIAEEmailFactory(self).reviewed, adversarial=True),
            (ACCEPTED, False): functools.partial(SIAEEmailFactory(self).reviewed, adversarial=False),
            (ADVERSARIAL_STAGE, False): SIAEEmailFactory(self).adversarial_stage,
            (NOTIFICATION_PENDING, True): SIAEEmailFactory(self).refused,
        }[(self.state, from_adversarial_stage)]()
        send_email_messages([email])

    @property
    def evaluation_is_final(self):
        return bool(self.final_reviewed_at or self.evaluation_campaign.ended_at)

    # fixme vincentporte : rsebille suggests to replace cached_property with prefetch_related
    @cached_property
    def state(self):

        # assuming the EvaluatedSiae instance is fully hydrated with its evaluated_job_applications
        # and evaluated_administrative_criteria before being called,
        # to prevent tons of additional queries in db.

        NOTIFICATION_PENDING_OR_REFUSED = (
            evaluation_enums.EvaluatedSiaeState.REFUSED
            if self.notified_at
            else evaluation_enums.EvaluatedSiaeState.NOTIFICATION_PENDING
        )

        STATES_PRIORITY = [
            # Low priority: all applications must have this state for the siae to have it
            evaluation_enums.EvaluatedSiaeState.ACCEPTED,
            evaluation_enums.EvaluatedSiaeState.REFUSED,
            evaluation_enums.EvaluatedSiaeState.SUBMITTED,
            evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
            evaluation_enums.EvaluatedSiaeState.PENDING,
            # High priority: if at least one application has this state, the siae will also
        ]

        def state_from(application):
            return {
                # pylint-disable=line-too-long
                evaluation_enums.EvaluatedJobApplicationsState.PENDING: evaluation_enums.EvaluatedSiaeState.PENDING,
                evaluation_enums.EvaluatedJobApplicationsState.PROCESSING: evaluation_enums.EvaluatedSiaeState.PENDING,
                evaluation_enums.EvaluatedJobApplicationsState.UPLOADED: evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,  # noqa: E501
                evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED: evaluation_enums.EvaluatedSiaeState.SUBMITTED,  # noqa: E501
                evaluation_enums.EvaluatedJobApplicationsState.REFUSED: evaluation_enums.EvaluatedSiaeState.REFUSED,
                evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2: evaluation_enums.EvaluatedSiaeState.REFUSED,
                evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED: evaluation_enums.EvaluatedSiaeState.ACCEPTED,
            }[application.compute_state()]

        state_from_applications = max(
            (state_from(eval_job_app) for eval_job_app in self.evaluated_job_applications.all()),
            key=STATES_PRIORITY.index,
            default=evaluation_enums.EvaluatedSiaeState.PENDING,
        )

        if state_from_applications in {
            evaluation_enums.EvaluatedSiaeState.PENDING,
            evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
        }:
            # SIAE did not submit proof
            return NOTIFICATION_PENDING_OR_REFUSED if self.evaluation_is_final else state_from_applications

        if state_from_applications == evaluation_enums.EvaluatedSiaeState.SUBMITTED:
            # if DDETS did not review proof, accept them
            return (
                evaluation_enums.EvaluatedSiaeState.ACCEPTED if self.evaluation_is_final else state_from_applications
            )

        # state_from_applications is either REFUSED or ACCEPTED here
        assert state_from_applications in {
            evaluation_enums.EvaluatedSiaeState.ACCEPTED,
            evaluation_enums.EvaluatedSiaeState.REFUSED,
        }, state_from_applications

        if self.reviewed_at and not self.evaluation_is_final:
            return evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE

        if (
            self.final_reviewed_at is None
            and self.evaluation_campaign.ended_at
            # reviewed_at is always set during the campaign.
            and any(
                eval_admin_crit.submitted_at > self.reviewed_at
                for eval_job_app in self.evaluated_job_applications.all()
                for eval_admin_crit in eval_job_app.evaluated_administrative_criteria.all()
            )
        ):
            return evaluation_enums.EvaluatedSiaeState.ACCEPTED

        if state_from_applications == evaluation_enums.EvaluatedSiaeState.REFUSED:
            if self.evaluation_is_final:
                return NOTIFICATION_PENDING_OR_REFUSED
            return evaluation_enums.EvaluatedSiaeState.REFUSED
        return evaluation_enums.EvaluatedSiaeState.ACCEPTED


class EvaluatedJobApplicationQuerySet(models.QuerySet):
    def viewable(self):
        viewable_campaigns = EvaluationCampaign.objects.viewable()
        return self.filter(evaluated_siae__evaluation_campaign__in=viewable_campaigns)


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

    objects = EvaluatedJobApplicationQuerySet.as_manager()

    class Meta:
        verbose_name = "Auto-prescription"
        verbose_name_plural = "Auto-prescriptions"

    def __str__(self):
        return f"{self.job_application}"

    def compute_state(self):
        STATES_PRIORITY = [
            # Low priority: all criteria must have this state for the evaluated job application to have it
            evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_enums.EvaluatedJobApplicationsState.REFUSED,
            evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED,
            evaluation_enums.EvaluatedJobApplicationsState.UPLOADED,
            evaluation_enums.EvaluatedJobApplicationsState.PROCESSING,
            # High priority: if at least one criteria has this state, the evaluated job application will also
        ]

        def state_from(criteria):
            if criteria.proof_url == "":
                return evaluation_enums.EvaluatedJobApplicationsState.PROCESSING
            if criteria.submitted_at is None:
                return evaluation_enums.EvaluatedJobApplicationsState.UPLOADED
            return {
                # pylint-disable=line-too-long
                evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING: evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED: evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED: evaluation_enums.EvaluatedJobApplicationsState.REFUSED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2: evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,  # noqa: E501
            }[criteria.review_state]

        return max(
            (state_from(criteria) for criteria in self.evaluated_administrative_criteria.all()),
            key=STATES_PRIORITY.index,
            default=evaluation_enums.EvaluatedJobApplicationsState.PENDING,
        )

    @property
    def should_select_criteria(self):
        state = self.compute_state()
        if state == evaluation_enums.EvaluatedJobApplicationsState.PENDING:
            return evaluation_enums.EvaluatedJobApplicationsSelectCriteriaState.PENDING

        if not self.evaluated_siae.reviewed_at and state in [
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


class EvaluatedAdministrativeCriteriaQuerySet(models.QuerySet):
    def viewable(self):
        viewable_campaigns = EvaluationCampaign.objects.viewable()
        return self.filter(evaluated_job_application__evaluated_siae__evaluation_campaign__in=viewable_campaigns)


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
    uploaded_at = models.DateTimeField(verbose_name="Téléversé le", blank=True, null=True)
    submitted_at = models.DateTimeField(verbose_name="Transmis le", blank=True, null=True)
    review_state = models.CharField(
        verbose_name="Vérification",
        max_length=10,
        choices=evaluation_enums.EvaluatedAdministrativeCriteriaState.choices,
        default=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
    )

    objects = EvaluatedAdministrativeCriteriaQuerySet.as_manager()

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


class Sanctions(models.Model):
    evaluated_siae = models.OneToOneField(
        EvaluatedSiae,
        on_delete=models.CASCADE,
        verbose_name="SIAE évaluée",
    )
    training_session = models.TextField(
        blank=True,
        verbose_name="Détails de la participation à une session de présentation de l’auto-prescription",
    )
    suspension_dates = InclusiveDateRangeField(
        blank=True,
        null=True,
        verbose_name="Retrait de la capacité d’auto-prescription",
    )
    subsidy_cut_percent = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name="Pourcentage de retrait de l’aide au poste",
    )
    subsidy_cut_dates = InclusiveDateRangeField(
        blank=True,
        null=True,
        verbose_name="Dates de retrait de l’aide au poste",
    )
    deactivation_reason = models.TextField(
        blank=True,
        verbose_name="Explication du déconventionnement de la structure",
    )
    no_sanction_reason = models.TextField(blank=True, verbose_name="Explication de l’absence de sanction")

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="subsidy_cut_consistency",
                violation_error_message=(
                    "Le pourcentage et la date de début de retrait de l’aide au poste doivent être renseignés."
                ),
                check=models.Q(subsidy_cut_percent__isnull=True, subsidy_cut_dates__isnull=True)
                | models.Q(subsidy_cut_percent__isnull=False, subsidy_cut_dates__isnull=False),
            ),
        ]
        verbose_name_plural = "sanctions"

    def __str__(self):
        return f"{self.__class__.__name__} pour {self.evaluated_siae}"

    def count_active(self):
        return (
            bool(self.training_session)
            + bool(self.suspension_dates)
            + bool(self.subsidy_cut_dates)
            + bool(self.deactivation_reason)
        )
