import logging

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.emails import get_email_text_template
from itou.utils.validators import alphanumeric

logger = logging.getLogger(__name__)


class Approval(models.Model):
    """
    Store approval(s) (or `agrément` in French) of a user.
    """

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
        super().clean()

    @property
    def accepted_by(self):
        if not self.job_application:
            return None
        return (
            self.job_application.logs.select_related("user")
            .get(to_state=JobApplicationWorkflow.STATE_ACCEPTED)
            .user
        )

    def send_number_by_email(self):
        context = {"approval": self}
        subject = "approvals/email/approval_number_subject.txt"
        body = "approvals/email/approval_number_body.txt"
        email = mail.EmailMessage(
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[self.accepted_by.email],
            subject=get_email_text_template(subject, context),
            body=get_email_text_template(body, context),
        )
        email.send()

    @staticmethod
    def get_next_number():
        last_approval = Approval.objects.order_by("created_at").last()
        if last_approval:
            return int(last_approval.number) + 1
        return None
