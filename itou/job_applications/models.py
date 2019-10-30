import logging
import uuid

from django.conf import settings
from django.core import mail
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_xworkflows import models as xwf_models

from itou.utils.emails import get_email_text_template


logger = logging.getLogger(__name__)


class JobApplicationWorkflow(xwf_models.Workflow):
    """
    The JobApplication workflow.
    https://django-xworkflows.readthedocs.io/
    """

    STATE_NEW = "new"
    STATE_PROCESSING = "processing"
    STATE_POSTPONED = "postponed"
    STATE_ACCEPTED = "accepted"
    STATE_REFUSED = "refused"
    STATE_OBSOLETE = "obsolete"

    STATE_CHOICES = (
        (STATE_NEW, _("Nouvelle candidature")),
        (STATE_PROCESSING, _("Candidature à l'étude")),
        (STATE_POSTPONED, _("Embauche pour plus tard")),
        (STATE_ACCEPTED, _("Embauche acceptée")),
        (STATE_REFUSED, _("Embauche déclinée")),
        (STATE_OBSOLETE, _("Embauché ailleurs")),
    )

    states = STATE_CHOICES

    TRANSITION_PROCESS = "process"
    TRANSITION_POSTPONE = "postpone"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_REFUSE = "refuse"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, _("Étudier la candidature")),
        (TRANSITION_POSTPONE, _("Reporter la candidature")),
        (TRANSITION_ACCEPT, _("Accepter l'embauche")),
        (TRANSITION_REFUSE, _("Décliner la candidature")),
        (TRANSITION_RENDER_OBSOLETE, _("Rendre obsolete la candidature")),
    )

    transitions = (
        (TRANSITION_PROCESS, STATE_NEW, STATE_PROCESSING),
        (TRANSITION_POSTPONE, STATE_PROCESSING, STATE_POSTPONED),
        (TRANSITION_ACCEPT, [STATE_PROCESSING, STATE_POSTPONED], STATE_ACCEPTED),
        (TRANSITION_REFUSE, STATE_PROCESSING, STATE_REFUSED),
        (
            TRANSITION_RENDER_OBSOLETE,
            [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED],
            STATE_OBSOLETE,
        ),
    )

    initial_state = STATE_NEW

    log_model = "job_applications.JobApplicationTransitionLog"


class JobApplicationQuerySet(models.QuerySet):
    def siae_member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(to_siae__members=user, to_siae__members__is_active=True)

    def pendind(self):
        return self.filter(
            state__in=[
                JobApplicationWorkflow.STATE_NEW,
                JobApplicationWorkflow.STATE_PROCESSING,
                JobApplicationWorkflow.STATE_POSTPONED,
            ]
        )


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    An "unsolicited" job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    SENDER_KIND_JOB_SEEKER = "job_seeker"
    SENDER_KIND_PRESCRIBER = "prescriber"
    SENDER_KIND_SIAE_STAFF = "siae_staff"

    SENDER_KIND_CHOICES = (
        (SENDER_KIND_JOB_SEEKER, _("Demandeur d'emploi")),
        (SENDER_KIND_PRESCRIBER, _("Prescripteur")),
        (SENDER_KIND_SIAE_STAFF, _("Employeur (SIAE)")),
    )

    REFUSAL_REASON_DID_NOT_COME = "did_not_come"
    REFUSAL_REASON_UNAVAILABLE = "unavailable"
    REFUSAL_REASON_NON_ELIGIBLE = "non_eligible"
    REFUSAL_REASON_ELIGIBILITY_DOUBT = "eligibility_doubt"
    REFUSAL_REASON_INCOMPATIBLE = "incompatible"
    REFUSAL_REASON_PREVENT_OBJECTIVES = "prevent_objectives"
    REFUSAL_REASON_NO_POSITION = "no_position"
    REFUSAL_REASON_OTHER = "other"

    REFUSAL_REASON_CHOICES = (
        (REFUSAL_REASON_DID_NOT_COME, _("Candidat non venu ou non joignable")),
        (
            REFUSAL_REASON_UNAVAILABLE,
            _("Candidat indisponible ou non intéressé par le poste"),
        ),
        (REFUSAL_REASON_NON_ELIGIBLE, _("Candidat non éligible")),
        (
            REFUSAL_REASON_ELIGIBILITY_DOUBT,
            _(
                "Doute sur l'éligibilité du candidat (penser à renvoyer la personne vers un prescripteur)"
            ),
        ),
        (
            REFUSAL_REASON_INCOMPATIBLE,
            _(
                "Un des freins à l'emploi du candidat est incompatible avec le poste proposé"
            ),
        ),
        (
            REFUSAL_REASON_PREVENT_OBJECTIVES,
            _(
                "L'embauche du candidat empêche la réalisation des objectifs du dialogue de gestion"
            ),
        ),
        (REFUSAL_REASON_NO_POSITION, _("Pas de poste ouvert en ce moment")),
        (REFUSAL_REASON_OTHER, _("Autre")),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Demandeur d'emploi"),
        on_delete=models.CASCADE,
        related_name="job_applications",
    )

    # Who send the job application. It can be the same user as `job_seeker`
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Émetteur"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_applications_sent",
    )

    sender_kind = models.CharField(
        verbose_name=_("Type de l'émetteur"),
        max_length=10,
        choices=SENDER_KIND_CHOICES,
        default=SENDER_KIND_PRESCRIBER,
    )

    # When the sender is an SIAE staff member, keep a track of his current SIAE.
    # Not implemented yet, but this could allow an SIAE to apply to itself.
    sender_siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name=_("SIAE émettrice"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    # When the sender is a prescriber, keep a track of his current organization (if any).
    sender_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name=_("Organisation du prescripteur émettrice"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    to_siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name=_("SIAE destinataire"),
        on_delete=models.CASCADE,
        related_name="job_applications_received",
    )

    state = xwf_models.StateField(
        JobApplicationWorkflow, verbose_name=_("État"), db_index=True
    )

    # Jobs in which the job seeker is interested (optional).
    jobs = models.ManyToManyField(
        "jobs.Appellation", verbose_name=_("Métiers recherchés"), blank=True
    )

    message = models.TextField(verbose_name=_("Message de candidature"), blank=True)
    answer = models.TextField(verbose_name=_("Message de réponse"), blank=True)
    refusal_reason = models.CharField(
        verbose_name=_("Motifs de refus"),
        max_length=30,
        choices=REFUSAL_REASON_CHOICES,
        blank=True,
    )

    created_at = models.DateTimeField(
        verbose_name=_("Date de création"), default=timezone.now, db_index=True
    )
    updated_at = models.DateTimeField(
        verbose_name=_("Date de modification"), blank=True, null=True, db_index=True
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
    def process(self, *args, **kwargs):
        pass

    @xwf_models.transition()
    def accept(self, *args, **kwargs):
        # Mark other related job applications as obsolete.
        for job_application in self.job_seeker.job_applications.exclude(
            pk=self.pk
        ).pendind():
            job_application.render_obsolete(*args, **kwargs)

    @xwf_models.transition()
    def refuse(self, *args, **kwargs):
        pass

    @xwf_models.transition()
    def render_obsolete(self, *args, **kwargs):
        pass

    # Emails.

    def get_siae_recipents_email_list(self):
        return list(
            self.to_siae.members.filter(is_active=True).values_list("email", flat=True)
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

    @property
    def pretty_to_state(self):
        choices = dict(JobApplicationWorkflow.STATE_CHOICES)
        return choices[self.to_state]
