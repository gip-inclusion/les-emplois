import collections
import logging

from dateutil.relativedelta import relativedelta
from unidecode import unidecode

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.emails import get_email_text_template
from itou.utils.validators import alphanumeric

logger = logging.getLogger(__name__)


class CommonApprovalMixin:
    """
    A set of methods shared by both Approval and PoleEmploiApproval models.
    """

    # A period after expiry of an Approval during which a person cannot obtain a new one.
    YEARS_BEFORE_NEW_APPROVAL = 2

    @property
    def is_valid(self):
        now = timezone.now().date()
        return (self.start_at <= now <= self.end_at) or (self.start_at >= now)

    @property
    def time_since_end(self):
        return relativedelta(timezone.now().date(), self.end_at)

    @property
    def can_obtain_new_approval(self):
        return self.time_since_end.years > self.YEARS_BEFORE_NEW_APPROVAL or (
            self.time_since_end.years == self.YEARS_BEFORE_NEW_APPROVAL
            and self.time_since_end.days > 0
        )


class CommonApprovalQuerySet(models.QuerySet):
    """
    A QuerySet shared by both Approval and PoleEmploiApproval models.
    """

    def valid(self):
        now = timezone.now().date()
        return self.filter(Q(start_at__lte=now, end_at__gte=now) | Q(start_at__gte=now))


class Approval(models.Model, CommonApprovalMixin):
    """
    Store approvals (`agréments` in French) delivered by Itou.
    Another name is "PASS IAE".
    """

    # This prefix is used by the ASP system to identify itou as the issuer of a number.
    NUMBER_PREFIX = "99999"

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
    start_at = models.DateField(verbose_name=_("Date de début"), blank=True, null=True)
    end_at = models.DateField(verbose_name=_("Date de fin"), blank=True, null=True)
    job_application = models.ForeignKey(
        "job_applications.JobApplication",
        verbose_name=_("Candidature d'origine"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    number_sent_by_email = models.BooleanField(
        verbose_name=_("Numéro envoyé par email"), default=False
    )
    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now
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
        super().save(*args, **kwargs)

    def clean(self):
        if self.end_at <= self.start_at:
            raise ValidationError(
                _("La date de fin doit être postérieure à la date de début.")
            )
        if not self.pk and self.user.approvals.valid().exists():
            raise ValidationError(
                _(
                    f"Un agrément dans le futur ou en cours de validité existe déjà "
                    f"pour {self.user.get_full_name()} ({self.user.email})."
                )
            )
        super().clean()

    def send_number_by_email(self):
        if not self.job_application or not self.job_application.accepted_by:
            raise RuntimeError(_("Unable to determine the recipient email address."))
        context = {"approval": self}
        subject = "approvals/email/approval_number_subject.txt"
        body = "approvals/email/approval_number_body.txt"
        email = mail.EmailMessage(
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[self.job_application.accepted_by.email],
            subject=get_email_text_template(subject, context),
            body=get_email_text_template(body, context),
        )
        email.send()

    @staticmethod
    def get_next_number(date_of_hiring=None):
        """
        Find next "PASS IAE" number.

        Structure of a "PASS IAE" number (12 chars):
            NUMBER_PREFIX (5 chars) + YEAR WITHOUT CENTURY (2 chars) + NUMBER (5 chars)

        Rule:
            The "PASS IAE"'s year is equal to the start year of the `JobApplication.date_of_hiring`.
        """
        date_of_hiring = date_of_hiring or timezone.now().date()
        year = date_of_hiring.strftime("%Y")
        last_approval = (
            Approval.objects.filter(start_at__year=year).order_by("created_at").last()
        )
        if last_approval:
            next_number = int(last_approval.number) + 1
            return str(next_number)
        year_2_chars = date_of_hiring.strftime("%y")
        return f"{Approval.NUMBER_PREFIX}{year_2_chars}00001"


class PoleEmploiApprovalManager(models.Manager):
    def find_for(self, first_name, last_name, birthdate):
        """
        Returns all available entries for the given `first_name`, `last_name`
        and `birthdate` (in an ideal case there is only 1 result).
        """
        first_name = PoleEmploiApproval.name_format(first_name)
        last_name = PoleEmploiApproval.name_format(last_name)
        qs = self.filter(
            first_name=first_name, last_name=last_name, birthdate=birthdate
        )
        if not qs.exists():
            # Try with `birth_name` instead of `last_name.
            qs = self.filter(
                first_name=first_name, birth_name=last_name, birthdate=birthdate
            )
        return qs


class PoleEmploiApproval(models.Model, CommonApprovalMixin):
    """
    Store approvals (`agréments` in French) delivered by Pôle emploi.

    These are either legacy approvals or approvals issued in parallel to
    Itou's approvals because the 2 systems have to co-exist before Itou
    is fully deployed all over France.

    Thus, before Itou can deliver an approval, we have to check if there
    isn't already a valid Pôle emploi's approval.

    This check can only be done on the triplet `first_name` + `last_name`
    + `birthdate` and with the custom format of names used by Pôle emploi.
    It's far from ideal…

    This table is populated and updated through the `import_pe_approvals`
    admin command.
    """

    pe_structure_code = models.CharField(_("Code structure Pôle emploi"), max_length=5)
    pe_regional_id = models.CharField(_("Code regional Pôle emploi"), max_length=8)
    number = models.CharField(verbose_name=_("Numéro"), max_length=18, unique=True)
    first_name = models.CharField(_("Prénom"), max_length=150, db_index=True)
    last_name = models.CharField(_("Nom"), max_length=150, db_index=True)
    birth_name = models.CharField(_("Nom de naissance"), max_length=150, db_index=True)
    # TODO: make `birthdate` mandatory as soon as the data is available.
    birthdate = models.DateField(
        verbose_name=_("Date de naissance"), null=True, blank=True, db_index=True
    )
    start_at = models.DateField(verbose_name=_("Date de début"))
    end_at = models.DateField(verbose_name=_("Date de fin"))
    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now
    )

    objects = PoleEmploiApprovalManager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = _("Agrément Pôle emploi")
        verbose_name_plural = _("Agréments Pôle emploi")

    def __str__(self):
        return self.number

    @staticmethod
    def name_format(name):
        """
        Format `name` in the same way as it is in the Pôle emploi export file:
        Upper-case ASCII transliterations of Unicode text.
        """
        return unidecode(name.strip()).upper()


class ApprovalsChecker:
    """
    TODO
    """

    RESULT = collections.namedtuple("ApprovalCheckerResult", ["code", "result"])

    # Result codes.
    FOUND = "FOUND"
    CAN_OBTAIN_NEW_APPROVAL = "CAN_OBTAIN_NEW_APPROVAL"
    CANNOT_OBTAIN_NEW_APPROVAL = "CANNOT_OBTAIN_NEW_APPROVAL"
    MULTIPLE_RESULTS = "MULTIPLE_RESULTS"

    def __init__(self, user):
        self.user = user

    def _get_latest_approval(self):
        try:
            return Approval.objects.filter(user=self.user).latest("start_at")
        except Approval.DoesNotExist:
            return None

    def _get_pole_emploi_approvals(self):
        return PoleEmploiApproval.objects.find_for(
            self.user.first_name, self.user.last_name, self.user.birthdate
        )

    def _check_single_approval(self, approval):
        if approval.is_valid:
            return self.RESULT(code=self.FOUND, result=approval)
        if approval.can_obtain_new_approval:
            return self.RESULT(code=self.CAN_OBTAIN_NEW_APPROVAL, result=approval)
        return self.RESULT(code=self.CANNOT_OBTAIN_NEW_APPROVAL, result=approval)

    def check(self):

        approval = self._get_latest_approval()

        if approval:
            return self._check_single_approval(approval)

        pole_emploi_approvals = self._get_pole_emploi_approvals()

        if not pole_emploi_approvals:
            return self.RESULT(code=self.CAN_OBTAIN_NEW_APPROVAL, result=None)

        if pole_emploi_approvals.count() > 1:
            return self.RESULT(code=self.MULTIPLE_RESULTS, result=pole_emploi_approvals)

        return self._check_single_approval(pole_emploi_approvals.first())
