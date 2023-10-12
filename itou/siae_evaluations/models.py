from pathlib import Path

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
from itou.utils.validators import validate_html

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

    if institution.kind != InstitutionKind.DDETS_IAE:
        raise ValidationError(f"Sélectionnez une institution de type {InstitutionKind.DDETS_IAE}")


def create_campaigns_and_calendar(
    evaluated_period_start_at,
    evaluated_period_end_at,
    adversarial_stage_start_date,
    institution_ids=None,
):
    """
    Create a campaign for each institution whose kind is DDETS IAE (possibly limited by institution_ids).
    This method is intented to be executed manually, until it will be automised.
    """

    name = (
        f"contrôle pour la période du {evaluated_period_start_at:%d/%m/%Y} " f"au {evaluated_period_end_at:%d/%m/%Y}"
    )

    institutions = Institution.objects.filter(kind=InstitutionKind.DDETS_IAE)
    if institution_ids:
        institutions = institutions.filter(pk__in=institution_ids)

    calendar, _ = Calendar.objects.get_or_create(
        name=name,
        defaults={"adversarial_stage_start": adversarial_stage_start_date},
    )
    evaluation_campaign_list = EvaluationCampaign.objects.bulk_create(
        EvaluationCampaign(
            calendar=calendar,
            evaluated_period_start_at=evaluated_period_start_at,
            evaluated_period_end_at=evaluated_period_end_at,
            institution=institution,
            name=name,
        )
        for institution in institutions
    )

    # Send notification.
    if evaluation_campaign_list:
        send_email_messages(
            CampaignEmailFactory(evaluation_campaign).ratio_to_select()
            for evaluation_campaign in evaluation_campaign_list
        )

    return len(evaluation_campaign_list)


class CampaignAlreadyPopulatedException(Exception):
    pass


class Calendar(models.Model):
    """
    Campaigns taking place at the same time share the same calendar.
    """

    name = models.CharField(verbose_name="nom", max_length=100, null=True)
    adversarial_stage_start = models.DateField(verbose_name="début de la phase contradictoire")
    html = models.TextField(verbose_name="contenu", validators=[validate_html])

    class Meta:
        verbose_name = "calendrier"

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        if not self.html:
            file_path = Path(settings.APPS_DIR) / "templates" / "siae_evaluations" / "default_calendar_html.html"
            with open(file_path, encoding="utf-8") as file:
                self.html = file.read()
        super().save(*args, **kwargs)


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
    - is run by one institution which kind is DDETS IAE,
    - According to a control agenda (ie : from 01.04.2022 to 30.06.2022)
    - on self-approvals made by siaes in the department of the institution (ie : departement 14),
    - during the evaluated period (ie : from 01.01.2021 to 31.12.2021).
    """

    name = models.CharField(verbose_name="nom de la campagne d'évaluation", max_length=100, blank=False, null=False)

    # dates of execution of the campaign
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    percent_set_at = models.DateTimeField(verbose_name="date de paramétrage de la sélection", blank=True, null=True)
    evaluations_asked_at = models.DateTimeField(
        verbose_name="date de notification du contrôle aux Siaes", blank=True, null=True
    )
    ended_at = models.DateTimeField(verbose_name="date de clôture de la campagne", blank=True, null=True)
    # When SIAE submissions are frozen, notify institutions:
    # - on the day submissions are frozen, and
    # - 7 days after submissions have been frozen.
    submission_freeze_notified_at = models.DateTimeField(
        verbose_name="notification des DDETS après blocage des soumissions SIAE",
        help_text="Date de dernière notification des DDETS après blocage des soumissions SIAE",
        null=True,
        editable=False,
    )

    # dates of the evaluated period
    # to do later : add coherence controls between campaign.
    # Campaign B for one institution cannot start before the end of campaign A of the same institution
    evaluated_period_start_at = models.DateField(
        verbose_name="date de début de la période contrôlée", blank=False, null=False
    )
    evaluated_period_end_at = models.DateField(
        verbose_name="date de fin de la période contrôlée", blank=False, null=False
    )

    institution = models.ForeignKey(
        "institutions.Institution",
        on_delete=models.CASCADE,
        related_name="evaluation_campaigns",
        verbose_name="DDETS IAE responsable du contrôle",
        validators=[validate_institution],
    )

    chosen_percent = models.PositiveIntegerField(
        verbose_name="pourcentage de sélection",
        default=evaluation_enums.EvaluationChosenPercent.DEFAULT,
        validators=[
            MinValueValidator(evaluation_enums.EvaluationChosenPercent.MIN),
            MaxValueValidator(evaluation_enums.EvaluationChosenPercent.MAX),
        ],
    )
    calendar = models.ForeignKey(
        Calendar,
        on_delete=models.SET_NULL,
        verbose_name="calendrier",
        null=True,
    )

    objects = EvaluationCampaignQuerySet.as_manager()

    class Meta:
        verbose_name = "campagne"
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

    def freeze(self, freeze_at):
        EvaluatedSiae.objects.filter(evaluation_campaign=self, submission_freezed_at__isnull=True).update(
            submission_freezed_at=freeze_at
        )

    def transition_to_adversarial_phase(self):
        now = timezone.now()
        emails = []
        accept_by_default = []
        transition_to_adversarial_stage = []
        auto_validation = []
        for evaluated_siae in self.evaluated_siaes.select_related(
            "evaluation_campaign__institution", "siae"
        ).prefetch_related("evaluated_job_applications__evaluated_administrative_criteria"):
            state = evaluated_siae.state
            email_factory = SIAEEmailFactory(evaluated_siae)
            if evaluated_siae.reviewed_at is not None:
                if state == evaluation_enums.EvaluatedSiaeState.ACCEPTED:
                    emails.append(email_factory.accepted(adversarial=False))
                elif state == evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE:
                    emails.append(email_factory.adversarial_stage())
                else:
                    # This shouldn't happen
                    raise ValueError(f"Unexpected {state=} for {evaluated_siae=} in transition_to_adversarial_stage()")
            else:
                if state in [
                    evaluation_enums.EvaluatedSiaeState.PENDING,
                    evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
                ]:
                    evaluated_siae.reviewed_at = now
                    transition_to_adversarial_stage.append(evaluated_siae)
                    emails.append(email_factory.forced_to_adversarial_stage())
                elif state == evaluation_enums.EvaluatedSiaeState.SUBMITTED:
                    evaluated_siae.reviewed_at = now
                    evaluated_siae.final_reviewed_at = now
                    accept_by_default.append(evaluated_siae)
                    emails.append(email_factory.force_accepted())
                else:
                    # evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE needs a reviewed_at
                    assert state in (
                        evaluation_enums.EvaluatedSiaeState.ACCEPTED,
                        evaluation_enums.EvaluatedSiaeState.REFUSED,
                    ), state
                    # The DDETS IAE set the review_state on all documents but forgot to submit its review
                    # The validation is automatically triggered by this transition to adversarial phase
                    auto_validation.append(evaluated_siae)
                    evaluated_siae.reviewed_at = now
                    if state == evaluation_enums.EvaluatedSiaeState.ACCEPTED:
                        emails.append(email_factory.accepted(adversarial=False))
                        evaluated_siae.final_reviewed_at = now
                    else:
                        emails.append(email_factory.adversarial_stage())

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
            accept_by_default + transition_to_adversarial_stage + auto_validation,
            ["reviewed_at", "final_reviewed_at"],
        )
        # Unfreeze all SIAEs to start adversarial stage
        EvaluatedSiae.objects.filter(evaluation_campaign=self, submission_freezed_at__isnull=False).update(
            submission_freezed_at=None
        )
        self.submission_freeze_notified_at = None
        self.save(update_fields=["submission_freeze_notified_at"])

    def close(self):
        now = timezone.now()
        if not self.ended_at:
            self.ended_at = now
            self.save(update_fields=["ended_at"])
            evaluated_siaes = (
                EvaluatedSiae.objects.filter(evaluation_campaign=self)
                .filter(notified_at=None)
                .prefetch_related("evaluated_job_applications__evaluated_administrative_criteria")
            )
            has_siae_to_notify = False
            siae_without_proofs = []
            emails = []
            for evaluated_siae in evaluated_siaes:
                if evaluated_siae.final_reviewed_at is None:
                    criterias = [
                        crit
                        for jobapp in evaluated_siae.evaluated_job_applications.all()
                        for crit in jobapp.evaluated_administrative_criteria.all()
                    ]
                    if len(criterias) == 0 or any(crit.submitted_at is None for crit in criterias):
                        siae_without_proofs.append(evaluated_siae)
                        has_siae_to_notify = True

                    if evaluated_siae.state_from_applications in (
                        evaluation_enums.EvaluatedSiaeState.ACCEPTED,
                        evaluation_enums.EvaluatedSiaeState.REFUSED,
                    ):
                        # The DDETS set the review_state on all documents but forgot to submit its review
                        # The validation is automatically triggered by this transition
                        evaluated_siae.final_reviewed_at = now
                        evaluated_siae.save(update_fields=["final_reviewed_at"])
                        if evaluated_siae.state_from_applications == evaluation_enums.EvaluatedSiaeState.ACCEPTED:
                            emails.append(SIAEEmailFactory(evaluated_siae).accepted(adversarial=True))
                        else:
                            emails.append(SIAEEmailFactory(evaluated_siae).refused())
                elif evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED:
                    emails.append(SIAEEmailFactory(evaluated_siae).refused())
                elif evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.ACCEPTED:
                    if evaluated_siae.reviewed_at != evaluated_siae.final_reviewed_at:
                        # This check ensures that the acceptance happened in the adversarial stage
                        # and not the amicable one
                        emails.append(SIAEEmailFactory(evaluated_siae).accepted(adversarial=True))
                # Computing the state is costly, avoid it when possible.
                if not has_siae_to_notify:
                    has_siae_to_notify |= evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.REFUSED

            emails.extend(
                SIAEEmailFactory(evaluated_siae).refused_no_proofs() for evaluated_siae in siae_without_proofs
            )
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
        verbose_name="contrôle",
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
    reviewed_at = models.DateTimeField(verbose_name="contrôlée le", blank=True, null=True)
    # Refused documents from the phase amiable can be uploaded again, a second
    # refusal is final (phase contradictoire).
    final_reviewed_at = models.DateTimeField(verbose_name="contrôle définitif le", blank=True, null=True)

    # At the end of each phase ("amiable" and "contradictoire"), the institutions have 2 weeks
    # during which the employers cannot submit new documents
    submission_freezed_at = models.DateTimeField(
        verbose_name="transmission bloquée pour la SIAE le", blank=True, null=True
    )

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
        verbose_name = "entreprise contrôlée"
        verbose_name_plural = "entreprises contrôlées"
        unique_together = ("evaluation_campaign", "siae")
        constraints = [
            models.CheckConstraint(
                name="final_reviewed_at_only_after_reviewed_at",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle définitif sans une date de premier contrôle antérieure"
                ),
                check=models.Q(final_reviewed_at__isnull=True)
                | models.Q(reviewed_at__isnull=False, final_reviewed_at__gte=F("reviewed_at")),
            ),
        ]

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

    @property
    def can_submit(self):
        return not self.submission_freezed_at and self.state == evaluation_enums.EvaluatedSiaeState.SUBMITTABLE

    @property
    def should_display_pending_action_warning(self):
        return not self.submission_freezed_at and self.state in (
            evaluation_enums.EvaluatedSiaeState.PENDING,
            evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
            evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE,
        )
        # if SUBMITTED, the SIAE cannot do anything until the DDETS reviews the documents
        # if ACCEPTED, it is either because the DDETS is currently reviewing or because it is fully acccepted
        # if REFUSED, it is either because the DDETS is currently reviewing or because it is fully refused

    def review(self):
        ACCEPTED = evaluation_enums.EvaluatedSiaeState.ACCEPTED
        REFUSED = evaluation_enums.EvaluatedSiaeState.REFUSED
        ADVERSARIAL_STAGE = evaluation_enums.EvaluatedSiaeState.ADVERSARIAL_STAGE
        current_state = self.state

        now = timezone.now()
        if current_state == ACCEPTED:
            self.reviewed_at = now
            self.final_reviewed_at = now
        elif current_state == REFUSED:
            self.reviewed_at = now
        elif current_state == ADVERSARIAL_STAGE:
            self.final_reviewed_at = now
        else:
            raise TypeError(f"Cannot review an “{self.__class__.__name__}” with status “{self.state}”.")
        self.save()
        # Invalidate the cache, a review changes the state of the evaluation.
        del self.state_from_applications

    @property
    def evaluation_is_final(self):
        return bool(self.final_reviewed_at or self.evaluation_campaign.ended_at)

    # fixme vincentporte : rsebille suggests to replace cached_property with prefetch_related
    @cached_property
    def state_from_applications(self):
        # assuming the EvaluatedSiae instance is fully hydrated with its evaluated_job_applications
        # and evaluated_administrative_criteria before being called,
        # to prevent tons of additional queries in db.

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
                evaluation_enums.EvaluatedJobApplicationsState.PENDING: evaluation_enums.EvaluatedSiaeState.PENDING,
                evaluation_enums.EvaluatedJobApplicationsState.PROCESSING: evaluation_enums.EvaluatedSiaeState.PENDING,
                evaluation_enums.EvaluatedJobApplicationsState.UPLOADED: evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,  # noqa: E501
                evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED: evaluation_enums.EvaluatedSiaeState.SUBMITTED,  # noqa: E501
                evaluation_enums.EvaluatedJobApplicationsState.REFUSED: evaluation_enums.EvaluatedSiaeState.REFUSED,
                evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2: evaluation_enums.EvaluatedSiaeState.REFUSED,
                evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED: evaluation_enums.EvaluatedSiaeState.ACCEPTED,
            }[application.compute_state()]

        return max(
            (state_from(eval_job_app) for eval_job_app in self.evaluated_job_applications.all()),
            key=STATES_PRIORITY.index,
            default=evaluation_enums.EvaluatedSiaeState.PENDING,
        )

    @property
    def state(self):
        state_from_applications = self.state_from_applications

        if state_from_applications in {
            evaluation_enums.EvaluatedSiaeState.PENDING,
            evaluation_enums.EvaluatedSiaeState.SUBMITTABLE,
        }:
            # SIAE did not submit proof
            return evaluation_enums.EvaluatedSiaeState.REFUSED if self.evaluation_is_final else state_from_applications

        if state_from_applications == evaluation_enums.EvaluatedSiaeState.SUBMITTED:
            # if DDETS IAE did not review proof, accept them
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

        return state_from_applications


class EvaluatedJobApplicationQuerySet(models.QuerySet):
    def viewable(self):
        viewable_campaigns = EvaluationCampaign.objects.viewable()
        return self.filter(evaluated_siae__evaluation_campaign__in=viewable_campaigns)


class EvaluatedJobApplication(models.Model):
    STATES_PRIORITY = [
        # Low priority: all criteria must have this state for the evaluated job application to have it
        evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
        evaluation_enums.EvaluatedJobApplicationsState.REFUSED,
        evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED,
        evaluation_enums.EvaluatedJobApplicationsState.UPLOADED,
        evaluation_enums.EvaluatedJobApplicationsState.PROCESSING,
        evaluation_enums.EvaluatedJobApplicationsState.PENDING,
        # High priority: if at least one criteria has this state, the evaluated job application will also
    ]

    job_application = models.ForeignKey(
        "job_applications.JobApplication",
        verbose_name="candidature",
        on_delete=models.CASCADE,
        related_name="evaluated_job_applications",
    )

    evaluated_siae = models.ForeignKey(
        EvaluatedSiae,
        verbose_name="SIAE évaluée",
        on_delete=models.CASCADE,
        related_name="evaluated_job_applications",
    )
    labor_inspector_explanation = models.TextField(verbose_name="commentaires de l'inspecteur du travail", blank=True)

    objects = EvaluatedJobApplicationQuerySet.as_manager()

    class Meta:
        verbose_name = "auto-prescription"

    def __str__(self):
        return f"{self.job_application}"

    def compute_state(self):
        def state_from(criteria):
            if criteria.proof_url == "":
                return evaluation_enums.EvaluatedJobApplicationsState.PROCESSING
            if criteria.submitted_at is None:
                return evaluation_enums.EvaluatedJobApplicationsState.UPLOADED
            return {
                evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING: evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED: evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED: evaluation_enums.EvaluatedJobApplicationsState.REFUSED,  # noqa: E501
                evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2: evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,  # noqa: E501
            }[criteria.review_state]

        return max(
            (state_from(criteria) for criteria in self.evaluated_administrative_criteria.all()),
            key=self.STATES_PRIORITY.index,
            default=evaluation_enums.EvaluatedJobApplicationsState.PENDING,
        )

    def hide_state_from_siae(self):
        """Hide in-progress evaluation from SIAE, until results are official."""
        if self.evaluated_siae.submission_freezed_at is None:
            return False
        adversarial_stage_start = self.evaluated_siae.evaluation_campaign.calendar.adversarial_stage_start
        if (
            timezone.localdate()
            <=
            # submission_freezed_at is reset with EvaluationCampaign.transition_to_adversarial_phase, which immediately
            # shows their state to SIAEs.
            # On the day of the transition, keep phase 2bis active so that SIAE don’t see their state until the admin
            # action in the admin to transition to adversarial stage is performed.
            adversarial_stage_start
        ):
            # Phase 2bis.
            return True
        # Phase 3bis.
        state_is_from_phase2 = all(
            # SIAE did not submit new documents, show evaluation from phase 2.
            crit.submitted_at and crit.submitted_at < self.evaluated_siae.reviewed_at
            for crit in self.evaluated_administrative_criteria.all()
        )
        return not state_is_from_phase2

    def compute_state_for_siae(self):
        real_state = self.compute_state()
        if self.hide_state_from_siae():
            submitted_state = evaluation_enums.EvaluatedJobApplicationsState.SUBMITTED
            real_state_priority = self.STATES_PRIORITY.index(real_state)
            submitted_state_priority = self.STATES_PRIORITY.index(submitted_state)
            if real_state_priority < submitted_state_priority:
                return submitted_state
        return real_state

    @property
    def should_select_criteria(self):
        if not self.evaluated_siae.submission_freezed_at:
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
        verbose_name="critère administratif",
        on_delete=models.CASCADE,
        related_name="evaluated_administrative_criteria",
    )

    evaluated_job_application = models.ForeignKey(
        EvaluatedJobApplication,
        verbose_name="candidature évaluée",
        on_delete=models.CASCADE,
        related_name="evaluated_administrative_criteria",
    )

    proof_url = models.URLField(max_length=500, verbose_name="lien vers le justificatif", blank=True)
    proof = models.ForeignKey("files.File", on_delete=models.CASCADE, blank=True, null=True)
    uploaded_at = models.DateTimeField(verbose_name="téléversé le", blank=True, null=True)
    submitted_at = models.DateTimeField(verbose_name="transmis le", blank=True, null=True)
    review_state = models.CharField(
        verbose_name="vérification",
        max_length=10,
        choices=evaluation_enums.EvaluatedAdministrativeCriteriaState.choices,
        default=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
    )

    objects = EvaluatedAdministrativeCriteriaQuerySet.as_manager()

    class Meta:
        verbose_name = "critère administratif"
        verbose_name_plural = "critères administratifs"
        unique_together = ("administrative_criteria", "evaluated_job_application")
        ordering = ["evaluated_job_application", "administrative_criteria"]

    def __str__(self):
        return f"{self.evaluated_job_application} - {self.administrative_criteria}"

    def can_upload(self):
        if self.evaluated_job_application.evaluated_siae.submission_freezed_at:
            return False
        if self.submitted_at is None:
            return True

        return (
            self.review_state == evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
            and self.evaluated_job_application.evaluated_siae.reviewed_at
        )

    def review_state_for_siae(self):
        if self.evaluated_job_application.hide_state_from_siae():
            return evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        return self.review_state


class Sanctions(models.Model):
    evaluated_siae = models.OneToOneField(
        EvaluatedSiae,
        on_delete=models.CASCADE,
        verbose_name="SIAE évaluée",
    )
    training_session = models.TextField(
        blank=True,
        verbose_name="détails de la participation à une session de présentation de l’auto-prescription",
    )
    suspension_dates = InclusiveDateRangeField(
        blank=True,
        null=True,
        verbose_name="retrait de la capacité d’auto-prescription",
    )
    subsidy_cut_percent = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        verbose_name="pourcentage de retrait de l’aide au poste",
    )
    subsidy_cut_dates = InclusiveDateRangeField(
        blank=True,
        null=True,
        verbose_name="dates de retrait de l’aide au poste",
    )
    deactivation_reason = models.TextField(
        blank=True,
        verbose_name="explication du déconventionnement de la structure",
    )
    no_sanction_reason = models.TextField(blank=True, verbose_name="explication de l’absence de sanction")

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
