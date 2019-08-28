import logging
import uuid

from django.conf import settings
from django.core import mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from anymail.exceptions import AnymailRequestsAPIError
from django_xworkflows import models as xwf_models

from itou.prescribers.models import Prescriber
from itou.siaes.models import Siae
from itou.utils.emails import get_email_text_template


logger = logging.getLogger(__name__)


class JobRequestWorkflow(xwf_models.Workflow):

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

    log_model = "job_applications.JobRequestTransitionLog"


class JobRequest(xwf_models.WorkflowEnabled, models.Model):
    """
    An "unsolicited" Job application request.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Demandeur d'emploi"),
        on_delete=models.CASCADE,
        related_name="job_requests_sent",
    )

    siae = models.ForeignKey(
        Siae,
        verbose_name=_("SIAE"),
        on_delete=models.CASCADE,
        related_name="job_requests_received",
    )

    prescriber_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Prescripteur"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_requests_prescribed",
    )
    # The prescriber can be a member of multiple organizations.
    # Keep track of the current one.
    prescriber = models.ForeignKey(
        Prescriber,
        verbose_name=_("Organisation du prescripteur"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    state = xwf_models.StateField(
        JobRequestWorkflow, verbose_name=_("État"), db_index=True
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

    class Meta:
        verbose_name = _("Candidature")
        verbose_name_plural = _("Candidatures")

    def __init__(self, *args, **kwargs):
        self.notifications = JobRequestNotifications(self)
        super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @xwf_models.transition()
    def send(self, *args, **kwargs):
        try:
            email = self.notifications.new_for_siae()
            email.send()
        except AnymailRequestsAPIError:
            logger.error(
                f"Email couldn't be sent during `send` transition for JobRequest `{self.id}`"
            )
            raise xwf_models.AbortTransition()

    @xwf_models.transition()
    def accept(self, *args, **kwargs):
        try:
            connection = mail.get_connection()
            emails = [self.notifications.accept_for_job_seeker()]
            if self.prescriber_user:
                emails.append(self.notifications.accept_for_prescriber())
            connection.send_messages(emails)
        except AnymailRequestsAPIError:
            logger.error(
                f"Email couldn't be sent during `accept` transition for JobRequest `{self.id}`"
            )
            raise xwf_models.AbortTransition()

    @xwf_models.transition()
    def reject(self, *args, **kwargs):
        pass

    @xwf_models.transition()
    def render_obsolete(self, *args, **kwargs):
        pass


class JobRequestNotifications:
    """
    The purpose of this class is purely organisational.
    """

    def __init__(self, job_request):
        self.job_request = job_request

    def get_siae_recipents_email_list(self):
        return list(
            self.job_request.siae.members.filter(is_active=True).values_list(
                "email", flat=True
            )
        )

    def get_email_message(self, from_email, to, context, subject, body):
        return mail.EmailMessage(
            from_email=from_email,
            to=to,
            subject=get_email_text_template(subject, context),
            body=get_email_text_template(body, context),
        )

    def new_for_siae(self):
        from_email = settings.DEFAULT_FROM_EMAIL
        to = self.get_siae_recipents_email_list()
        context = {
            "jobs": self.job_request.jobs.all(),
            "job_seeker": self.job_request.job_seeker,
            "motivation_message": self.job_request.motivation_message,
            "prescriber": self.job_request.prescriber,
            "prescriber_user": self.job_request.prescriber_user,
        }
        subject = "job_applications/email/new_for_siae_subject.txt"
        body = "job_applications/email/new_for_siae_body.txt"
        return self.get_email_message(from_email, to, context, subject, body)

    def accept_for_job_seeker(self):
        from_email = settings.DEFAULT_FROM_EMAIL
        to = [self.job_request.job_seeker.email]
        context = {
            "job_seeker": self.job_request.job_seeker,
            "acceptance_message": self.job_request.acceptance_message,
            "siae": self.job_request.siae,
        }
        subject = "job_applications/email/accept_for_job_seeker_subject.txt"
        body = "job_applications/email/accept_for_job_seeker_body.txt"
        return self.get_email_message(from_email, to, context, subject, body)

    def accept_for_prescriber(self):
        from_email = settings.DEFAULT_FROM_EMAIL
        to = [self.job_request.prescriber_user.email]
        context = {
            "job_seeker": self.job_request.job_seeker,
            "acceptance_message": self.job_request.acceptance_message,
            "siae": self.job_request.siae,
        }
        subject = "job_applications/email/accept_for_prescriber_subject.txt"
        body = "job_applications/email/accept_for_prescriber_body.txt"
        return self.get_email_message(from_email, to, context, subject, body)


class JobRequestTransitionLog(xwf_models.BaseTransitionLog):
    """
    https://django-xworkflows.readthedocs.io/en/latest/internals.html#django_xworkflows.models.BaseTransitionLog
    """

    job_request = models.ForeignKey(
        JobRequest, related_name="logs", on_delete=models.CASCADE
    )

    # Extra data to keep about transitions.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL
    )

    # Name of the field where the modified object goes.
    MODIFIED_OBJECT_FIELD = "job_request"

    # Define extra logging attributes
    EXTRA_LOG_ATTRIBUTES = (("user", "user", None),)

    class Meta:
        verbose_name = _("Log des transitions de la candidature")
        verbose_name_plural = _("Log des transitions des candidatures")
        ordering = ["-timestamp"]
