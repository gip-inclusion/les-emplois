import datetime
import logging
import time

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from unidecode import unidecode

from itou.utils.emails import get_email_message
from itou.utils.models import DateRange
from itou.utils.validators import alphanumeric


logger = logging.getLogger(__name__)


class CommonApprovalMixin(models.Model):
    """
    Abstract model for fields and methods common to both `Approval`
    and `PoleEmploiApproval` models.
    """

    # Default duration of an approval.
    DEFAULT_APPROVAL_YEARS = 2
    # `Période de carence` in French.
    # A period after expiry of an Approval during which a person cannot
    # obtain a new one except from an "authorized prescriber".
    WAITING_PERIOD_YEARS = 2

    # Due to COVID lockdown restrictions, the end date of overlapping approvals
    # has been extended by 3 months.
    LOCKDOWN_START_AT = datetime.date(2020, 3, 17)
    LOCKDOWN_END_AT = datetime.date(2020, 6, 16)
    LOCKDOWN_EXTENSION_DELAY_MONTHS = 3

    start_at = models.DateField(verbose_name=_("Date de début"), default=timezone.now, db_index=True)
    end_at = models.DateField(verbose_name=_("Date de fin"), default=timezone.now, db_index=True)
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)

    class Meta:
        abstract = True

    @property
    def is_valid(self):
        now = timezone.now().date()
        return (self.start_at <= now <= self.end_at) or (self.start_at >= now)

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.now().date() <= self.end_at

    @property
    def waiting_period_end(self):
        return self.end_at + relativedelta(years=self.WAITING_PERIOD_YEARS)

    @property
    def is_in_waiting_period(self):
        now = timezone.now().date()
        return self.end_at < now <= self.waiting_period_end

    @property
    def waiting_period_has_elapsed(self):
        now = timezone.now().date()
        return now > self.waiting_period_end

    @property
    def originates_from_itou(self):
        return self.number.startswith(Approval.ASP_ITOU_PREFIX)

    @property
    def is_pass_iae(self):
        """
        Returns True if the approval has been issued by Itou, False otherwise.
        """
        return isinstance(self, Approval)

    @property
    def duration(self):
        return self.end_at - self.start_at

    @property
    def overlaps_covid_lockdown(self):
        ends_before_lockdown = self.end_at < self.LOCKDOWN_START_AT
        starts_after_lockdown = self.start_at > self.LOCKDOWN_END_AT
        return not (ends_before_lockdown or starts_after_lockdown)


class CommonApprovalQuerySet(models.QuerySet):
    """
    A QuerySet shared by both `Approval` and `PoleEmploiApproval` models.
    """

    @property
    def valid_lookup(self):
        now = timezone.now().date()
        return Q(start_at__lte=now, end_at__gte=now) | Q(start_at__gte=now)

    def valid(self):
        return self.filter(self.valid_lookup)

    def invalid(self):
        return self.exclude(self.valid_lookup)


class Approval(CommonApprovalMixin):
    """
    Store "PASS IAE" whose former name was "approval" ("agréments" in French)
    issued by Itou.

    A number starting with `ASP_ITOU_PREFIX` means it has been created by Itou.

    Otherwise, it was previously created by Pôle emploi (and initially found
    in `PoleEmploiApproval`) and re-issued by Itou as a PASS IAE.
    """

    # This prefix is used by the ASP system to identify itou as the issuer of a number.
    ASP_ITOU_PREFIX = settings.ASP_ITOU_PREFIX

    # The period of time during which it is possible to prolong a PASS IAE before it ends.
    PROLONGATION_PERIOD_BEFORE_APPROVAL_END_MONTHS = 3

    # Error messages.
    ERROR_PASS_IAE_SUSPENDED_FOR_USER = _(
        "Votre PASS IAE est suspendu. Vous ne pouvez pas postuler pendant la période de suspension."
    )
    ERROR_PASS_IAE_SUSPENDED_FOR_PROXY = _(
        "Le PASS IAE du candidat est suspendu. Vous ne pouvez pas postuler "
        "pour lui pendant la période de suspension."
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Demandeur d'emploi"),
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    number = models.CharField(
        verbose_name=_("Numéro"),
        max_length=12,
        help_text=_("12 caractères alphanumériques."),
        validators=[alphanumeric, MinLengthValidator(12)],
        unique=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("Créé par"), null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = models.Manager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = _("Agrément")
        verbose_name_plural = _("Agréments")
        ordering = ["-created_at"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        self.clean()

        already_exists = bool(self.pk)

        if not already_exists and hasattr(self, "number") and hasattr(self, "start_at"):

            # Prevent a database integrity error during automatic creation.
            # TODO: investigate UPSERT with ON CONFLICT to speed this up.
            if self.originates_from_itou:
                while Approval.objects.filter(number=self.number).exists():
                    self.number = self.get_next_number(self.start_at)

            # Handle COVID extensions for approvals originally issued by Pôle emploi.
            # Approvals issued by Itou have already been extended through SQL.
            if not self.originates_from_itou and self.overlaps_covid_lockdown:
                self.end_at = self.end_at + relativedelta(months=self.LOCKDOWN_EXTENSION_DELAY_MONTHS)

        super().save(*args, **kwargs)

    def clean(self):
        try:
            if self.end_at <= self.start_at:
                raise ValidationError(_("La date de fin doit être postérieure à la date de début."))
        except TypeError:
            # This can happen if `end_at` or `start_at` are empty or malformed
            # (e.g. when data comes from a form).
            pass
        already_exists = bool(self.pk)
        if not already_exists and hasattr(self, "user") and self.user.approvals.valid().exists():
            raise ValidationError(
                _(
                    f"Un agrément dans le futur ou en cours de validité existe déjà "
                    f"pour {self.user.get_full_name()} ({self.user.email})."
                )
            )
        super().clean()

    @property
    def number_with_spaces(self):
        """
        Insert spaces to format the number.
        """
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"

    @cached_property
    def can_be_deleted(self):
        state_accepted = self.jobapplication_set.model.state.STATE_ACCEPTED

        job_applications = self.jobapplication_set
        if job_applications.count() != 1:
            return False
        return self.jobapplication_set.get().state == state_accepted

    # Suspension.

    @cached_property
    def is_suspended(self):
        return self.suspension_set.in_progress().exists()

    @cached_property
    def suspensions_by_start_date_asc(self):
        return self.suspension_set.all().order_by("start_at")

    @cached_property
    def last_old_suspension(self):
        return self.suspensions_by_start_date_asc.old().last()

    @cached_property
    def can_be_suspended(self):
        return self.is_in_progress and not self.is_suspended

    def can_be_suspended_by_siae(self, siae):
        return (
            self.can_be_suspended
            and self.user.last_hire_was_made_by_siae(siae)
            and not self.user.last_accepted_job_application.can_be_cancelled
        )

    # Prolongation.

    @cached_property
    def has_pending_prolongation(self):
        return self.prolongation_set.pending().exists()

    @cached_property
    def prolongations_by_start_date_asc(self):
        return self.prolongation_set.validated().order_by("start_at")

    @property
    def is_open_to_prolongation(self):
        now = timezone.now().date()
        prolongation_threshold = self.end_at - relativedelta(
            months=self.PROLONGATION_PERIOD_BEFORE_APPROVAL_END_MONTHS
        )
        return prolongation_threshold <= now <= self.end_at

    @cached_property
    def can_be_prolonged(self):
        return self.is_open_to_prolongation and not self.is_suspended and not self.has_pending_prolongation

    def can_be_prolonged_by_siae(self, siae):
        return self.user.last_hire_was_made_by_siae(siae) and self.can_be_prolonged

    @staticmethod
    def get_next_number(hiring_start_at=None):
        """
        Find next "PASS IAE" number.

        Structure of a 12 chars "PASS IAE" number:
            ASP_ITOU_PREFIX (5 chars) + YEAR WITHOUT CENTURY (2 chars) + NUMBER (5 chars)

        Rule:
            The "PASS IAE"'s year is equal to the start year of the `JobApplication.hiring_start_at`.
        """
        hiring_start_at = hiring_start_at or timezone.now().date()
        year = hiring_start_at.strftime("%Y")
        last_itou_approval = (
            Approval.objects.filter(number__startswith=Approval.ASP_ITOU_PREFIX, start_at__year=year)
            .order_by("created_at")
            .last()
        )
        if last_itou_approval:
            if Approval.ASP_ITOU_PREFIX.isdigit():
                next_number = int(last_itou_approval.number) + 1
            else:
                # For some environment, the prefix is a string (ie. XXXXX or YYYYY).
                numeric_part = int(last_itou_approval.number.replace(Approval.ASP_ITOU_PREFIX, "")) + 1
                next_number = Approval.ASP_ITOU_PREFIX + str(numeric_part)
            return str(next_number)
        year_2_chars = hiring_start_at.strftime("%y")
        return f"{Approval.ASP_ITOU_PREFIX}{year_2_chars}00001"

    @staticmethod
    def get_default_end_date(start_at):
        return start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS) - relativedelta(days=1)

    @classmethod
    def get_or_create_from_valid(cls, approvals_wrapper):
        """
        Returns an existing valid Approval or create a new entry from
        a pre-existing valid PoleEmploiApproval by copying its data.
        """
        approval = approvals_wrapper.latest_approval
        if not approval.is_valid or not isinstance(approval, (cls, PoleEmploiApproval)):
            raise RuntimeError(_("Invalid approval."))
        if isinstance(approval, cls):
            return approval
        approval_from_pe = cls(
            start_at=approval.start_at,
            end_at=approval.end_at,
            user=approvals_wrapper.user,
            # Only store 12 chars numbers.
            number=approval.number[:12],
        )
        approval_from_pe.save()
        return approval_from_pe


class SuspensionQuerySet(models.QuerySet):
    @property
    def in_progress_lookup(self):
        now = timezone.now().date()
        return models.Q(start_at__lte=now, end_at__gte=now)

    def in_progress(self):
        return self.filter(self.in_progress_lookup)

    def not_in_progress(self):
        return self.exclude(self.in_progress_lookup)

    def old(self):
        now = timezone.now().date()
        return self.filter(end_at__lt=now)


class Suspension(models.Model):
    """
    A PASS IAE (or approval) issued by Itou can be directly suspended by an SIAE,
    without intervention of a prescriber or a posteriori control.

    When a suspension is saved/edited/deleted, the end date of its approval is
    automatically pushed back or forth with a PostgreSQL trigger:
    `trigger_update_approval_end_at`.
    """

    # Min duration: none.
    # Max duration: 6 months (could be adjusted according to user feedback).
    # 6-months suspensions can be consecutive and there can be any number of them.
    MAX_DURATION_MONTHS = 6

    class Reason(models.TextChoices):
        SICKNESS = "SICKNESS", _("Arrêt pour longue maladie")
        MATERNITY = "MATERNITY", _("Congé de maternité")
        INCARCERATION = "INCARCERATION", _("Incarcération")
        TRIAL_OUTSIDE_IAE = (
            "TRIAL_OUTSIDE_IAE",
            _("Période d'essai auprès d'un employeur ne relevant pas de l'insertion par l'activité économique"),
        )
        DETOXIFICATION = "DETOXIFICATION", _("Période de cure pour désintoxication")
        FORCE_MAJEURE = (
            "FORCE_MAJEURE",
            _(
                "Raison de force majeure conduisant le salarié à quitter son emploi ou toute autre "
                "situation faisant l'objet d'un accord entre les acteurs membres du CTA"
            ),
        )

    approval = models.ForeignKey(Approval, verbose_name=_("PASS IAE"), on_delete=models.CASCADE)
    start_at = models.DateField(verbose_name=_("Date de début"), default=timezone.now, db_index=True)
    end_at = models.DateField(verbose_name=_("Date de fin"), default=timezone.now, db_index=True)
    siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name=_("SIAE"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="approvals_suspended",
    )
    reason = models.CharField(verbose_name=_("Motif"), max_length=30, choices=Reason.choices, default=Reason.SICKNESS)
    reason_explanation = models.TextField(verbose_name=_("Explications supplémentaires"), blank=True)
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Créé par"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="approvals_suspended_set",
    )
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Mis à jour par"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    objects = models.Manager.from_queryset(SuspensionQuerySet)()

    class Meta:
        verbose_name = _("Suspension")
        verbose_name_plural = _("Suspensions")
        ordering = ["-start_at"]
        # Use an exclusion constraint to prevent overlapping date ranges.
        # This requires the btree_gist extension on PostgreSQL.
        # See "Tip of the Week" https://postgresweekly.com/issues/289
        # https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
        constraints = [
            ExclusionConstraint(
                name="exclude_overlapping_suspensions",
                expressions=(
                    (
                        DateRange("start_at", "end_at", RangeBoundary(inclusive_lower=True, inclusive_upper=True)),
                        RangeOperators.OVERLAPS,
                    ),
                    ("approval", RangeOperators.EQUAL),
                ),
            ),
        ]

    def __str__(self):
        return f"{self.pk} {self.start_at.strftime('%d/%m/%Y')} - {self.end_at.strftime('%d/%m/%Y')}"

    def save(self, *args, **kwargs):
        """
        The related Approval's end date is automatically pushed back/forth
        with a PostgreSQL trigger: `trigger_update_approval_end_at`.
        """
        if self.pk:
            self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        if self.reason == self.Reason.FORCE_MAJEURE and not self.reason_explanation:
            raise ValidationError({"reason_explanation": _("En cas de force majeure, veuillez préciser le motif.")})

        # No min duration: a suspension may last only 1 day.
        if self.end_at < self.start_at:
            raise ValidationError({"end_at": _("La date de fin doit être postérieure à la date de début.")})

        # A suspension cannot be in the future.
        if self.start_in_future:
            raise ValidationError({"start_at": _("La suspension ne peut pas commencer dans le futur.")})

        # The start of a suspension must be contained in its approval boundaries.
        if not self.start_in_approval_boundaries:
            raise ValidationError(
                {
                    "start_at": _(
                        f"La suspension ne peut pas commencer en dehors des limites du PASS IAE "
                        f"{self.approval.start_at.strftime('%d/%m/%Y')} - {self.approval.end_at.strftime('%d/%m/%Y')}."
                    )
                }
            )

        # A suspension cannot exceed max duration.
        max_end_at = self.get_max_end_at(self.start_at)
        if self.end_at > max_end_at:
            raise ValidationError(
                {
                    "end_at": _(
                        f"La durée totale ne peut excéder {self.MAX_DURATION_MONTHS} mois. "
                        f"Date de fin maximum: {max_end_at.strftime('%d/%m/%Y')}."
                    )
                }
            )

        # A suspension cannot overlap another one for the same SIAE.
        # This check is enforced by a constraint at the database level but
        # still required here to avoid a 500 server error "IntegrityError"
        # during form validation.
        if self.get_overlapping_suspensions().exists():
            overlap = self.get_overlapping_suspensions().first()
            raise ValidationError(
                {
                    "start_at": _(
                        f"La période chevauche une suspension déjà existante pour ce PASS IAE "
                        f"{overlap.start_at.strftime('%d/%m/%Y')} - {overlap.end_at.strftime('%d/%m/%Y')}."
                    )
                }
            )

    @property
    def duration(self):
        return self.end_at - self.start_at

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.now().date() <= self.end_at

    @property
    def start_in_future(self):
        return self.start_at > timezone.now().date()

    @property
    def start_in_approval_boundaries(self):
        return self.approval.start_at <= self.start_at <= self.approval.end_at

    def get_overlapping_suspensions(self):
        args = {
            "end_at__gte": self.start_at,
            "start_at__lte": self.end_at,
            "approval": self.approval,
        }
        return self._meta.model.objects.exclude(pk=self.pk).filter(**args)

    def can_be_handled_by_siae(self, siae):
        """
        Only the SIAE currently hiring the job seeker can handle a suspension.
        """
        cached_result = getattr(self, "_can_be_handled_by_siae_cache", None)
        if cached_result:
            return cached_result
        self._can_be_handled_by_siae_cache = self.is_in_progress and self.approval.user.last_hire_was_made_by_siae(
            siae
        )
        return self._can_be_handled_by_siae_cache

    @staticmethod
    def get_max_end_at(start_at):
        """
        Returns the maximum date on which a suspension can end.
        """
        return start_at + relativedelta(months=Suspension.MAX_DURATION_MONTHS) - relativedelta(days=1)

    @staticmethod
    def next_min_start_at(approval):
        """
        Returns the minimum date on which a suspension can begin.
        """
        if approval.last_old_suspension:
            return approval.last_old_suspension.end_at + relativedelta(days=1)
        return approval.user.last_accepted_job_application.hiring_start_at


class ProlongationQuerySet(models.QuerySet):
    @property
    def in_progress_lookup(self):
        now = timezone.now().date()
        return models.Q(start_at__lte=now, end_at__gte=now)

    def in_progress(self):
        return self.filter(self.in_progress_lookup)

    def not_in_progress(self):
        return self.exclude(self.in_progress_lookup)

    def pending(self):
        return self.filter(status=self.model.Status.PENDING)

    def validated(self):
        return self.filter(status=self.model.Status.VALIDATED)


class ProlongationManager(models.Manager):
    def get_cumulative_duration_for(self, approval, reason=None):
        """
        Returns the total duration of all prolongations of the given approval
        for the given reason (if any).
        """
        kwargs = {"approval": approval}
        if reason:
            kwargs["reason"] = reason
        duration = datetime.timedelta(0)
        for prolongation in self.validated().filter(**kwargs):
            duration += prolongation.duration
        return duration


class Prolongation(models.Model):
    """
    A prolongation can be issued by an SIAE for a PASS IAE.

    It must then be validated by a Pôle emploi agent because a self-validated
    prolongation made by an SIAE would increase the risk of staying on
    insertion for a candidate.

    When a prolongation is saved/edited/deleted, the end date of its approval
    is automatically pushed back or forth with a PostgreSQL trigger:
    `trigger_update_approval_end_at_for_prolongation`.
    """

    # Min duration: none.
    # Max duration: 12 months (but it depends on the `reason` field).
    MAX_DURATION_MONTHS = 12

    class Status(models.TextChoices):
        PENDING = "PENDING", _("À traiter")
        VALIDATED = "VALIDATED", _("Validée")
        REFUSED = "REFUSED", _("Refusée")

    class Reason(models.TextChoices):
        COMPLETE_TRAINING = "COMPLETE_TRAINING", _("Fin d'une formation (6 mois maximum)")
        RQTH = "RQTH", _("RQTH (12 mois maximum)")
        SENIOR = "SENIOR", _("50 ans et plus (12 mois maximum)")
        PARTICULAR_DIFFICULTIES = (
            "PARTICULAR_DIFFICULTIES",
            _(
                "Difficultés particulières qui font obstacle à l'insertion durable dans l’emploi "
                "(12 mois maximum dans la limite de 5 ans)"
            ),
        )

    MAX_CUMULATIVE_DURATION = {
        Reason.COMPLETE_TRAINING.value: {
            "duration": datetime.timedelta(days=365 * 0.5),
            "label": _("6 mois"),
        },
        Reason.PARTICULAR_DIFFICULTIES.value: {
            "duration": datetime.timedelta(days=365 * 5),
            "label": _("5 ans"),
        },
    }

    approval = models.ForeignKey(Approval, verbose_name=_("PASS IAE"), on_delete=models.CASCADE)
    start_at = models.DateField(verbose_name=_("Date de début"), default=timezone.now, db_index=True)
    end_at = models.DateField(verbose_name=_("Date de fin"), default=timezone.now, db_index=True)
    siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name=_("SIAE"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="approvals_prolongated",
    )
    reason = models.CharField(
        verbose_name=_("Motif"), max_length=30, choices=Reason.choices, default=Reason.COMPLETE_TRAINING
    )
    reason_explanation = models.TextField(verbose_name=_("Motivez la demande"), blank=True)

    status = models.CharField(
        verbose_name=_("Statut"),
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )
    status_updated_at = models.DateTimeField(verbose_name=_("Date de mise à jour du statut"), null=True)
    status_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Statut mis à jour par"),
        related_name="approvals_prolongations_status_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Créé par"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="approvals_prolongated_set",
    )
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Mis à jour par"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    objects = ProlongationManager.from_queryset(ProlongationQuerySet)()

    class Meta:
        verbose_name = _("Prolongation")
        verbose_name_plural = _("Prolongations")
        ordering = ["-start_at"]
        # Use an exclusion constraint to prevent overlapping date ranges.
        # This requires the btree_gist extension on PostgreSQL.
        # See "Tip of the Week" https://postgresweekly.com/issues/289
        # https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
        constraints = [
            ExclusionConstraint(
                name="exclude_overlapping_prolongations",
                expressions=(
                    (
                        # [start_at, end_at) (inclusive start, exclusive end).
                        # For prolongations: upper bound of preceding interval is the lower bound of the next.
                        DateRange("start_at", "end_at", RangeBoundary(inclusive_lower=True, inclusive_upper=False)),
                        RangeOperators.OVERLAPS,
                    ),
                    ("approval", RangeOperators.EQUAL),
                ),
            ),
        ]

    def __str__(self):
        return f"{self.pk} {self.start_at.strftime('%d/%m/%Y')} - {self.end_at.strftime('%d/%m/%Y')}"

    def save(self, *args, **kwargs):
        """
        The related Approval's end date is automatically pushed back/forth with
        a PostgreSQL trigger: `trigger_update_approval_end_at_for_prolongation`.
        """
        if self.pk:
            self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        # No min duration: a prolongation may last only 1 day.
        if self.end_at < self.start_at:
            raise ValidationError({"end_at": _("La date de fin doit être postérieure à la date de début.")})

        # A prolongation cannot exceed max duration.
        max_end_at = self.get_max_end_at(self.start_at, self.reason)
        if self.end_at > max_end_at:
            raise ValidationError(
                {
                    "end_at": _(
                        f'La durée totale est trop longue pour le motif "{self.get_reason_display()}". '
                        f"Date de fin maximum: {max_end_at.strftime('%d/%m/%Y')}."
                    )
                }
            )

        if self.reason == self.Reason.PARTICULAR_DIFFICULTIES.value:
            if self.siae.kind not in [self.siae.KIND_AI, self.siae.KIND_ACI]:
                raise ValidationError(_(f'Le motif "{self.get_reason_display()}" est réservé aux AI et ACI.'))

        # A prolongation cannot overlap another one for the same SIAE.
        # This check is enforced by a constraint at the database level but
        # still required here to avoid a 500 server error "IntegrityError"
        # during form validation.
        if self.get_overlapping_prolongations().exists():
            overlap = self.get_overlapping_prolongations().first()
            raise ValidationError(
                {
                    "start_at": _(
                        f"La période chevauche une prolongation déjà existante pour ce PASS IAE "
                        f"{overlap.start_at.strftime('%d/%m/%Y')} - {overlap.end_at.strftime('%d/%m/%Y')}."
                    )
                }
            )

        if self.has_reached_max_cumulative_duration(additional_duration=self.duration):
            raise ValidationError(
                _(
                    f"Vous ne pouvez pas cumuler des prolongations pendant plus de "
                    f'{self.MAX_CUMULATIVE_DURATION[self.reason]["label"]} '
                    f'pour le motif "{self.get_reason_display()}".'
                )
            )

    @property
    def duration(self):
        return self.end_at - self.start_at

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.now().date() <= self.end_at

    @property
    def email_new_prolongation_for_admin(self):
        to = [settings.ITOU_EMAIL_CONTACT]
        context = {
            "prolongation": self,
            "admin_url": reverse("admin:approvals_prolongation_change", args=[self.pk]),
        }
        subject = "approvals/email/new_prolongation_for_admin_subject.txt"
        body = "approvals/email/new_prolongation_for_admin_body.txt"
        return get_email_message(to, context, subject, body)

    def has_reached_max_cumulative_duration(self, additional_duration=None):
        if self.reason not in [self.Reason.COMPLETE_TRAINING.value, self.Reason.PARTICULAR_DIFFICULTIES.value]:
            return False

        cumulative_duration = Prolongation.objects.get_cumulative_duration_for(self.approval, reason=self.reason)
        if additional_duration:
            cumulative_duration += additional_duration

        return cumulative_duration > self.MAX_CUMULATIVE_DURATION[self.reason]["duration"]

    def get_overlapping_prolongations(self):
        args = {
            "start_at__lte": self.end_at,  # Inclusive start.
            "end_at__gt": self.start_at,  # Exclusive end.
            "approval": self.approval,
        }
        return self._meta.model.objects.exclude(pk=self.pk).filter(**args)

    @staticmethod
    def get_start_at(approval):
        """
        Returns the start date of the prolongation.
        """
        return approval.end_at

    @staticmethod
    def get_max_end_at(start_at, reason=None):
        """
        Returns the maximum date on which a prolongation can end.
        """
        max_duration_months = Prolongation.MAX_DURATION_MONTHS
        if reason == Prolongation.Reason.COMPLETE_TRAINING.value:
            max_duration_months = 6
        return start_at + relativedelta(months=max_duration_months) - relativedelta(days=1)


class PoleEmploiApprovalManager(models.Manager):
    def get_import_dates(self):
        """
        Return a list of import dates.
        [
            datetime.date(2020, 2, 23),
            datetime.date(2020, 4, 8),
            …
        ]

        It used to be used in the admin but it slowed it down.
        It's still used from time to time in django-admin shell.
        """
        return list(
            self
            # Remove default `Meta.ordering` to avoid an extra field being added to the GROUP BY clause.
            .order_by()
            .annotate(import_date=TruncDate("created_at"))
            .values_list("import_date", flat=True)
            .annotate(c=Count("id"))
        )

    def find_for(self, user):
        """
        Find existing Pôle emploi's approvals for the given user.

        We were told to check on `first_name` + `last_name` + `birthdate`
        but it's far from ideal:

        - the character encoding format is different between databases
        - there are no accents in the PE database
            => `format_name_as_pole_emploi()` is required to harmonize the formats
        - input errors in names are possible on both sides
        - there can be an inversion of first and last name fields
        - imported data can be poorly structured (first and last names in the same field)

        The only solution to ID a person between information systems would be to have
        a unique ID per user known by everyone (Itou, PE and the job seeker).

        Yet we don't have such an identifier.

        As a workaround, we rely on the combination of `pole_emploi_id` (non-unique
        but it is assumed that every job seeker knows his number) and `birthdate`.

        Their input formats can be checked to limit the risk of errors.
        """
        # Save some SQL queries.
        if not user.pole_emploi_id or not user.birthdate:
            return self.none()
        return self.filter(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate).order_by("-start_at")


class PoleEmploiApproval(CommonApprovalMixin):
    """
    Store approvals (`agréments` in French) delivered by Pôle emploi.

    Two approval's delivering systems co-exist. Pôle emploi's approvals
    are issued in parallel.

    Thus, before Itou can deliver an approval, we have to check this table
    to ensure that there isn't already a valid Pôle emploi's approval.

    This table is populated and updated through the `import_pe_approvals`
    admin command on a regular basis with data shared by Pôle emploi.

    If a valid Pôle emploi's approval is found, it's copied in the `Approval`
    at the time of issuance.
    """

    # Matches prescriber_organisation.code_safir_pole_emploi.
    pe_structure_code = models.CharField(_("Code structure Pôle emploi"), max_length=5)

    # The normal length of a number is 12 chars.
    # Sometimes the number ends with an extension ('A01', 'E02', 'P03', 'S04' etc.) that
    # increases the length to 15 chars.
    # Suffixes meaning in French:
    class Suffix(models.TextChoices):
        # `P`: Prolongation = la personne a besoin d'encore quelques mois
        P = "prolongation", _("Prolongation")
        # `E`: Extension = la personne est passée d'une structure à une autre
        E = "extension", _("Extension")
        # `A`: Interruption = la personne ne s'est pas présentée
        A = "interruption", _("Interruption")
        # `S`: Suspension = creux pendant la période justifié dans un cadre légal (incarcération, arrêt maladie etc.)
        S = "suspension", _("Suspension")

    # Parts of an Approval number:
    #     - first 5 digits = code SAFIR of the PE agency of the consultant creating the approval
    #     - next 2 digits = 2-digit year of delivery
    #     - next 5 digits = decision number with autonomous increment per PE agency, e.g.: 75631 14 10001
    #         - decisions are starting with 1
    #         - decisions starting with 0 are reserved for "Reprise des décisions", e.g.: 75631 14 00001
    #     - next 3 chars (optional suffix) = status change, e.g.: 75631 14 10001 E01
    #         - first char = kind of amendment:
    #             - E for "Extension"
    #             - S for "Suspension"
    #             - P for "Prolongation"
    #             - A for "Interruption"
    #         - next 2 digits = refer to the act number (e.g. E02 = second extension)
    # An Approval number is not modifiable, there is a new entry for each new status change.
    # Suffixes are not taken into account in Itou.
    number = models.CharField(verbose_name=_("Numéro"), max_length=15, unique=True)
    pole_emploi_id = models.CharField(_("Identifiant Pôle emploi"), max_length=8)
    first_name = models.CharField(_("Prénom"), max_length=150)
    last_name = models.CharField(_("Nom"), max_length=150)
    birth_name = models.CharField(_("Nom de naissance"), max_length=150)
    birthdate = models.DateField(verbose_name=_("Date de naissance"), default=timezone.now)

    objects = PoleEmploiApprovalManager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = _("Agrément Pôle emploi")
        verbose_name_plural = _("Agréments Pôle emploi")
        ordering = ["-start_at"]
        indexes = [models.Index(fields=["pole_emploi_id", "birthdate"], name="pe_id_and_birthdate_idx")]

    def __str__(self):
        return self.number

    @staticmethod
    def format_name_as_pole_emploi(name):
        """
        Format `name` in the same way as it is in the Pôle emploi export file:
        Upper-case ASCII transliterations of Unicode text.
        """
        return unidecode(name.strip()).upper()

    @property
    def number_with_spaces(self):
        """
        Insert spaces to format the number as in the Pôle emploi export file
        (number is stored without spaces).
        """
        if len(self.number) == 15:
            return f"{self.number[:5]} {self.number[5:7]} {self.number[7:12]} {self.number[12:]}"
        # 12 chars.
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"


class ApprovalsWrapper:
    """
    Wrapper that manipulates both `Approval` and `PoleEmploiApproval` models
    for a given user.

    This should be the only way to access approvals for a given job seeker.

    Pôle emploi is the historical issuing authority for approvals.
    At the end of 2019, Itou began to issue approvals (called PASS IAE) in
    parallel.
    During 2021, Itou should become the new sole issuing authority.
    But for the time being, 2 systems coexist.

    When a candidate applies for a job, it is necessary to:
        - check if Itou has already issued a PASS IAE
        - or check if Pôle emploi has already issued an approval

    Moreover, the status must be checked to be able to block applications
    in case of waiting period, suspension etc.

    This wrapper encapsulates all this logic for use in views and templates
    without having to manually search in two different tables.

    (Maybe a Manager would've been a better place for this logic).
    """

    # Status codes.
    NONE_FOUND = "NONE_FOUND"
    VALID = "VALID"
    IN_WAITING_PERIOD = "IN_WAITING_PERIOD"

    # Error messages.
    ERROR_CANNOT_OBTAIN_NEW_FOR_USER = _(
        "Vous avez terminé un parcours il y a moins de deux ans. "
        "Pour prétendre à nouveau à un parcours en structure d'insertion "
        "par l'activité économique vous devez rencontrer un prescripteur "
        "habilité : Pôle emploi, Mission Locale, CAP Emploi, etc."
    )
    ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY = _(
        "Le candidat a terminé un parcours il y a moins de deux ans. "
        "Pour prétendre à nouveau à un parcours en structure d'insertion "
        "par l'activité économique il doit rencontrer un prescripteur "
        "habilité : Pôle emploi, Mission Locale, CAP Emploi, etc."
    )

    def __init__(self, user):

        self.user = user
        self.latest_approval = None
        self.merged_approvals = self._merge_approvals()

        if not self.merged_approvals:
            self.status = self.NONE_FOUND
        else:
            self.latest_approval = self.merged_approvals[0]
            if self.latest_approval.is_valid:
                self.status = self.VALID
            elif self.latest_approval.waiting_period_has_elapsed:
                # The `Période de carence` is over. A job seeker can get a new Approval.
                self.latest_approval = None
                self.status = self.NONE_FOUND
            else:
                self.status = self.IN_WAITING_PERIOD

        # Only one of the following attributes can be True at a time.
        self.has_valid = self.status == self.VALID
        self.has_in_waiting_period = self.status == self.IN_WAITING_PERIOD

    def _merge_approvals(self):
        """
        Returns a list of merged unique `Approval` and `PoleEmploiApproval` objects.
        """
        approvals = list(Approval.objects.filter(user=self.user).order_by("-start_at"))

        # If an ongoing PASS IAE exists, consider it's the latest valid approval
        # even if a PoleEmploiApproval is more recent.
        if any(approval.is_valid for approval in approvals):
            return approvals

        approvals_numbers = [approval.number for approval in approvals]
        pe_approvals = [
            pe_approval
            for pe_approval in list(PoleEmploiApproval.objects.find_for(self.user))
            # A `PoleEmploiApproval` could already have been copied in `Approval`.
            if pe_approval not in approvals_numbers
        ]
        merged_approvals = approvals + pe_approvals
        # Sort by the most distant `end_at`, then by the earliest `start_at`.
        # This allows to always choose the longest and most recent approval.
        # Dates are converted to timestamp so that the subtraction operator
        # can be used in the lambda.
        return sorted(
            merged_approvals, key=lambda x: (-time.mktime(x.end_at.timetuple()), time.mktime(x.start_at.timetuple()))
        )

    @property
    def has_valid_pole_emploi_eligibility_diagnosis(self):
        """
        The existence of a valid `PoleEmploiApproval` implies that a diagnosis
        has been made outside of Itou.
        """
        return self.has_valid and not self.latest_approval.originates_from_itou
