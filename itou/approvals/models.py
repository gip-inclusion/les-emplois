import logging

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.emails import get_email_text_template
from itou.utils.validators import alphanumeric

logger = logging.getLogger(__name__)


class Approval(models.Model):
    """
    Store approval(s) (or `agrément` in French) of a user.
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
        if not self.pk and self.user.has_valid_approval():
            raise ValidationError(
                _(
                    f"Un agrément dans le futur ou en cours de validité existe déjà "
                    f"pour {self.user.get_full_name()} ({self.user.email})."
                )
            )
        super().clean()

    @property
    def is_valid(self):
        if self.start_at <= timezone.now().date() <= self.end_at:
            return True
        return False

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
