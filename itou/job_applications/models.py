import logging
import uuid

from django.conf import settings
from django.core import mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from anymail.exceptions import AnymailRequestsAPIError
from django_xworkflows import models as xwf_models

from itou.utils.emails import get_email_text_template


logger = logging.getLogger(__name__)


class JobApplicationWorkflow(xwf_models.Workflow):

    STATE_NEW = "new"
    STATE_PENDING_ANSWER = "pending_answer"
    STATE_ACCEPTED = "accepted"
    STATE_REJECTED = "rejected"
    STATE_OBSOLETE = "obsolete"

    STATE_CHOICES = (
        (STATE_NEW, _("Nouvelle candidature")),
        (STATE_PENDING_ANSWER, _("En attente de réponse")),
        (STATE_ACCEPTED, _("Candidature acceptée")),
        (STATE_REJECTED, _("Candidature rejetée")),
        (STATE_OBSOLETE, _("Obsolète")),  # The job seeker found another job.
    )

    states = STATE_CHOICES

    TRANSITION_SEND = "send"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_REJECT = "reject"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"

    TRANSITION_CHOICES = (
        (TRANSITION_SEND, _("Envoyer")),
        (TRANSITION_ACCEPT, _("Accepter")),
        (TRANSITION_REJECT, _("Refuser")),
        (TRANSITION_RENDER_OBSOLETE, _("Rendre obsolete")),
    )

    transitions = (
        (TRANSITION_SEND, STATE_NEW, STATE_PENDING_ANSWER),
        (TRANSITION_ACCEPT, STATE_PENDING_ANSWER, STATE_ACCEPTED),
        (TRANSITION_REJECT, STATE_PENDING_ANSWER, STATE_REJECTED),
        (TRANSITION_RENDER_OBSOLETE, [STATE_NEW, STATE_PENDING_ANSWER], STATE_OBSOLETE),
    )

    initial_state = STATE_NEW

    log_model = "job_applications.JobApplicationTransitionLog"


class JobApplicationQuerySet(models.QuerySet):
    def siae_member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(siae__members=user, siae__members__is_active=True)


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    An "unsolicited" job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Demandeur d'emploi"),
        on_delete=models.CASCADE,
        related_name="job_applications_sent",
    )

    siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name=_("SIAE"),
        on_delete=models.CASCADE,
        related_name="job_applications_received",
    )

    prescriber_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Prescripteur"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_applications_prescribed",
    )
    # The prescriber can be a member of multiple organizations.
    # Keep track of the current one.
    prescriber = models.ForeignKey(
        "prescribers.Prescriber",
        verbose_name=_("Organisation du prescripteur"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    state = xwf_models.StateField(
        JobApplicationWorkflow, verbose_name=_("État"), db_index=True
    )

    # Jobs in which the job seeker is interested (optional).
    jobs = models.ManyToManyField(
        "jobs.Appellation", verbose_name=_("Métiers recherchés"), blank=True
    )

    motivation_message = models.TextField(
        verbose_name=_("Message de candidature"), blank=True
    )
    acceptance_message = models.TextField(
        verbose_name=_("Message d'acceptation"), blank=True
    )
    rejection_message = models.TextField(verbose_name=_("Message de rejet"), blank=True)

    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now, db_index=True
    )
    updated_at = models.DateTimeField(
        verbose_name=_("Updated at"), blank=True, null=True, db_index=True
    )

    objects = models.Manager.from_queryset(JobApplicationQuerySet)()

    class Meta:
        verbose_name = _("Candidature")
        verbose_name_plural = _("Candidatures")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    # Workflow transitions.

    @xwf_models.transition()
    def send(self, *args, **kwargs):
        try:
            self.email_new_for_siae.send()
        except AnymailRequestsAPIError:
            logger.error(
                f"Email couldn't be sent during `send` transition for JobApplication `{self.id}`"
            )
            raise xwf_models.AbortTransition()

    @xwf_models.transition()
    def accept(self, *args, **kwargs):
        # TODO: mark other related job applications as obsolete.
        self.acceptance_message = kwargs["acceptance_message"]
        try:
            connection = mail.get_connection()
            emails = [self.email_accept_for_job_seeker]
            if self.prescriber_user:
                emails += [self.email_accept_for_prescriber]
            connection.send_messages(emails)
        except AnymailRequestsAPIError:
            logger.error(
                f"Email couldn't be sent during `accept` transition for JobApplication `{self.id}`"
            )
            raise xwf_models.AbortTransition()

    @xwf_models.transition()
    def reject(self, *args, **kwargs):
        self.rejection_message = kwargs["rejection_message"]
        try:
            connection = mail.get_connection()
            emails = [self.email_reject_for_job_seeker]
            if self.prescriber_user:
                emails += [self.email_reject_for_prescriber]
            connection.send_messages(emails)
        except AnymailRequestsAPIError:
            logger.error(
                f"Email couldn't be sent during `reject` transition for JobApplication `{self.id}`"
            )
            raise xwf_models.AbortTransition()

    @xwf_models.transition()
    def render_obsolete(self, *args, **kwargs):
        pass

    # Emails.

    def get_siae_recipents_email_list(self):
        return list(
            self.siae.members.filter(is_active=True).values_list("email", flat=True)
        )

    def get_email_message(
        self, to, context, subject, body, from_email=settings.DEFAULT_FROM_EMAIL
    ):
        return mail.EmailMessage(
            from_email=from_email,
            to=to,
            subject=get_email_text_template(subject, context),
            body=get_email_text_template(body, context),
        )

    @property
    def email_new_for_siae(self):
        to = self.get_siae_recipents_email_list()
        context = {"job_application": self}
        subject = "apply/email/new_for_siae_subject.txt"
        body = "apply/email/new_for_siae_body.txt"
        return self.get_email_message(to, context, subject, body)

    @property
    def email_accept_for_job_seeker(self):
        to = [self.job_seeker.email]
        context = {"job_application": self}
        subject = "apply/email/accept_for_job_seeker_subject.txt"
        body = "apply/email/accept_for_job_seeker_body.txt"
        return self.get_email_message(to, context, subject, body)

    @property
    def email_accept_for_prescriber(self):
        to = [self.prescriber_user.email]
        context = {"job_application": self}
        subject = "apply/email/accept_for_prescriber_subject.txt"
        body = "apply/email/accept_for_prescriber_body.txt"
        return self.get_email_message(to, context, subject, body)

    @property
    def email_reject_for_job_seeker(self):
        to = [self.job_seeker.email]
        context = {"job_application": self}
        subject = "apply/email/reject_for_job_seeker_subject.txt"
        body = "apply/email/reject_for_job_seeker_body.txt"
        return self.get_email_message(to, context, subject, body)

    @property
    def email_reject_for_prescriber(self):
        to = [self.prescriber_user.email]
        context = {"job_application": self}
        subject = "apply/email/reject_for_prescriber_subject.txt"
        body = "apply/email/reject_for_prescriber_body.txt"
        return self.get_email_message(to, context, subject, body)


class JobApplicationTransitionLog(xwf_models.BaseTransitionLog):
    """
    JobApplication's transition logs are stored in this table.
    https://django-xworkflows.readthedocs.io/en/latest/internals.html#django_xworkflows.models.BaseTransitionLog
    """

    MODIFIED_OBJECT_FIELD = "job_application"
    EXTRA_LOG_ATTRIBUTES = (("user", "user", None),)
    job_application = models.ForeignKey(
        JobApplication, related_name="logs", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = _("Log des transitions de la candidature")
        verbose_name_plural = _("Log des transitions des candidatures")
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.id)
