import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.timesince import timeuntil
from django.utils.translation import gettext_lazy as _
from unidecode import unidecode

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

    start_at = models.DateField(
        verbose_name=_("Date de début"), default=timezone.now, db_index=True
    )
    end_at = models.DateField(
        verbose_name=_("Date de fin"), default=timezone.now, db_index=True
    )
    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now
    )

    class Meta:
        abstract = True

    @property
    def is_valid(self):
        now = timezone.now().date()
        return (self.start_at <= now <= self.end_at) or (self.start_at >= now)

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
    def time_until_waiting_period(self):
        """
        Helper primarily used within templates whose sole purpose is to catch
        and display a custom message for the localized "0 minutes" otherwise
        returned by the built-in `timeuntil` template filter:
        https://docs.djangoproject.com/en/dev/ref/templates/builtins/#timeuntil
        """
        if not self.is_valid:
            return "0"
        now = timezone.now().date()
        if self.start_at > now:
            return "in_future"
        if self.end_at == now:
            return "0"
        return timeuntil(self.end_at, now)


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
    Store approvals (`agréments` in French). Another name is `PASS IAE`.

    A number starting with `ASP_ITOU_PREFIX` means it has been delivered
    through ITOU. Otherwise, it was delivered by Pôle emploi and initially
    found in `PoleEmploiApproval`.

    If an approval exists in this table it means that:
    - it has been delivered through Itou
    - but was created by either Itou or Pôle emploi
    """

    # This prefix is used by the ASP system to identify itou as the issuer of a number.
    ASP_ITOU_PREFIX = "99999"

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
        settings.AUTH_USER_MODEL,
        verbose_name=_("Créé par"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
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
        # Prevent a database integrity error during automatic creation.
        if not already_exists and hasattr(self, "number") and hasattr(self, "start_at"):
            if self.number.startswith(self.ASP_ITOU_PREFIX):
                while Approval.objects.filter(number=self.number).exists():
                    self.number = self.get_next_number(self.start_at)
        super().save(*args, **kwargs)

    def clean(self):
        try:
            if self.end_at <= self.start_at:
                raise ValidationError(
                    _("La date de fin doit être postérieure à la date de début.")
                )
        except TypeError:
            # This can happen if `end_at` or `start_at` are empty or malformed
            # (e.g. when data comes from a form).
            pass
        already_exists = bool(self.pk)
        if (
            not already_exists
            and hasattr(self, "user")
            and self.user.approvals.valid().exists()
        ):
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
        # pylint: disable=unsubscriptable-object
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"
        # pylint: enable=unsubscriptable-object

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
            Approval.objects.filter(
                number__startswith=Approval.ASP_ITOU_PREFIX, start_at__year=year
            )
            .order_by("created_at")
            .last()
        )
        if last_itou_approval:
            next_number = int(last_itou_approval.number) + 1
            return str(next_number)
        year_2_chars = hiring_start_at.strftime("%y")
        return f"{Approval.ASP_ITOU_PREFIX}{year_2_chars}00001"

    @staticmethod
    def get_default_end_date(start_at):
        return (
            start_at
            + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
            # TODO: ensure that subtracting 1 day is the right thing to do.
            - relativedelta(days=1)
        )

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


class PoleEmploiApprovalManager(models.Manager):
    def find_for(self, user):
        """
        Find an existing valid Pôle emploi's approval for the given user.

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
        return self.filter(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate
        ).order_by("-start_at")


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
    model when it is attached to a JobApplication.
    """

    pe_structure_code = models.CharField(_("Code structure Pôle emploi"), max_length=5)
    # The normal length of a number is 12 chars.
    # Sometimes the number ends with an extension ('A01', 'E02', 'P03', 'S04' etc.) that
    # increases the length to 15 chars.
    # Suffixes menaing:
    # - `P`: Prolongation
    # - `E`: Extension
    # - `A`: Interruption
    # - `S`: Suspension
    # The last two digits refer to the act number (e.g. E02 = second extension).
    # Suffixes are not taken into account in Itou yet but that might change.
    number = models.CharField(verbose_name=_("Numéro"), max_length=15, unique=True)
    pole_emploi_id = models.CharField(_("Identifiant Pôle emploi"), max_length=8)
    first_name = models.CharField(_("Prénom"), max_length=150)
    last_name = models.CharField(_("Nom"), max_length=150)
    birth_name = models.CharField(_("Nom de naissance"), max_length=150)
    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), default=timezone.now
    )

    objects = PoleEmploiApprovalManager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = _("Agrément Pôle emploi")
        verbose_name_plural = _("Agréments Pôle emploi")
        ordering = ["-start_at"]
        indexes = [
            models.Index(
                fields=["pole_emploi_id", "birthdate"], name="pe_id_and_birthdate_idx"
            )
        ]

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
        # pylint: disable=unsubscriptable-object
        if len(self.number) == 15:
            return f"{self.number[:5]} {self.number[5:7]} {self.number[7:12]} {self.number[12:]}"
        # 12 chars.
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"
        # pylint: enable=unsubscriptable-object


class ApprovalsWrapper:
    """
    Wrapper that manipulates both `Approval` and `PoleEmploiApproval` models.

    This should be the only way to access approvals for a given job seeker.
    """

    # Status codes.
    NONE_FOUND = "NONE_FOUND"
    VALID = "VALID"
    IN_WAITING_PERIOD = "IN_WAITING_PERIOD"
    WAITING_PERIOD_HAS_ELAPSED = "WAITING_PERIOD_HAS_ELAPSED"

    # Error messages.
    ERROR_CANNOT_OBTAIN_NEW_FOR_USER = _(
        "Vous avez terminé un parcours il y à moins de deux ans. "
        "Pour prétendre à nouveau à un parcours en structure d'insertion "
        "par l'activité économique vous devez rencontrer un prescripteur "
        "habilité : Pôle emploi, Mission Locale, CAP Emploi, etc."
    )
    ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY = _(
        "Le candidat a terminé un parcours il y à moins de deux ans. "
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
                self.status = self.WAITING_PERIOD_HAS_ELAPSED
            else:
                self.status = self.IN_WAITING_PERIOD

        # Only one of the following attributes can be True at a time.
        self.has_valid = self.status == self.VALID
        self.has_in_waiting_period = self.status == self.IN_WAITING_PERIOD

    def _merge_approvals(self):
        """
        Returns a list of merged unique `Approval` and `PoleEmploiApproval`
        objects ordered by most recent `start_at` dates.
        """
        approvals = list(Approval.objects.filter(user=self.user).order_by("-start_at"))
        approvals_numbers = [approval.number for approval in approvals]
        pe_approvals = [
            pe_approval
            for pe_approval in list(PoleEmploiApproval.objects.find_for(self.user))
            # A `PoleEmploiApproval` could already have been copied in `Approval`.
            if pe_approval not in approvals_numbers
        ]
        merged_approvals = approvals + pe_approvals
        return sorted(merged_approvals, key=lambda x: x.start_at, reverse=True)
