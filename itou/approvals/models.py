import logging

from dateutil.relativedelta import relativedelta
from unidecode import unidecode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.validators import alphanumeric


logger = logging.getLogger(__name__)


class CommonApprovalMixin(models.Model):
    """
    Abstract model for fields and methods common to both `Approval`
    and `PoleEmploiApproval` models.
    """

    # Default duration of an approval.
    DEFAULT_APPROVAL_YEARS = 2
    # A period after expiry of an Approval during which a person cannot obtain a new one
    # except from an "authorized prescriber".
    YEARS_BEFORE_NEW_APPROVAL = 2

    start_at = models.DateField(
        verbose_name=_("Date de début"), blank=True, null=True, db_index=True
    )
    end_at = models.DateField(
        verbose_name=_("Date de fin"), blank=True, null=True, db_index=True
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
    def time_since_end(self):
        return relativedelta(timezone.now().date(), self.end_at)

    @property
    def can_obtain_new(self):
        return self.time_since_end.years > self.YEARS_BEFORE_NEW_APPROVAL or (
            self.time_since_end.years == self.YEARS_BEFORE_NEW_APPROVAL
            and self.time_since_end.days > 0
        )


class CommonApprovalQuerySet(models.QuerySet):
    """
    A QuerySet shared by both `Approval` and `PoleEmploiApproval` models.
    """

    def valid(self):
        now = timezone.now().date()
        return self.filter(Q(start_at__lte=now, end_at__gte=now) | Q(start_at__gte=now))

    def invalid(self):
        now = timezone.now().date()
        return self.exclude(
            Q(start_at__lte=now, end_at__gte=now) | Q(start_at__gte=now)
        )


class Approval(CommonApprovalMixin):
    """
    Store approvals (`agréments` in French). Another name is `PASS IAE`.

    A number starting with `ASP_ITOU_PREFIX` means it has been delivered
    through ITOU. Otherwise, it was delivered by Pôle emploi and initially
    found in `PoleEmploiApproval`.
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
        if (
            not self.pk
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
            - relativedelta(days=1)
        )

    @classmethod
    def get_or_create_from_valid(cls, approval, user):
        """
        Returns an existing valid Approval or create a new entry from
        a pre-existing valid PoleEmploiApproval by copying its data.
        """
        if not approval.is_valid or not isinstance(approval, (cls, PoleEmploiApproval)):
            raise RuntimeError(_("Invalid approval."))
        if isinstance(approval, cls):
            return approval
        approval_from_pe = cls(
            start_at=approval.start_at,
            end_at=approval.end_at,
            user=user,
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
            => `name_format()` is required to harmonize the formats
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
    model.
    """

    pe_structure_code = models.CharField(_("Code structure Pôle emploi"), max_length=5)
    # The normal length of a number is 12 chars.
    # Sometimes the number ends with an extension ('A01', 'A02', 'A03' or 'S01') that
    # increases the length to 15 chars. Their meaning is yet unclear: we were told
    # `A01` means "interruption" and `S01` means "suspension".
    number = models.CharField(verbose_name=_("Numéro"), max_length=15, unique=True)
    pole_emploi_id = models.CharField(
        _("Identifiant Pôle emploi"), max_length=8, db_index=True
    )
    first_name = models.CharField(_("Prénom"), max_length=150, db_index=True)
    last_name = models.CharField(_("Nom"), max_length=150, db_index=True)
    birth_name = models.CharField(_("Nom de naissance"), max_length=150, db_index=True)
    # TODO: make `birthdate` mandatory as soon as the data is available.
    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), null=True, blank=True, db_index=True
    )

    objects = PoleEmploiApprovalManager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = _("Agrément Pôle emploi")
        verbose_name_plural = _("Agréments Pôle emploi")
        ordering = ["-start_at"]

    def __str__(self):
        return self.number

    @staticmethod
    def name_format(name):
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
    """

    # Status codes.
    VALID = "VALID"
    CAN_OBTAIN_NEW = "CAN_OBTAIN_NEW"
    CANNOT_OBTAIN_NEW = "CANNOT_OBTAIN_NEW"

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
            self.status = self.CAN_OBTAIN_NEW
        else:
            self.latest_approval = self.merged_approvals[0]
            if self.latest_approval.is_valid:
                self.status = self.VALID
            elif self.latest_approval.can_obtain_new:
                self.status = self.CAN_OBTAIN_NEW
            else:
                self.status = self.CANNOT_OBTAIN_NEW

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
