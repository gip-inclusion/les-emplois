import datetime
import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.db import models
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_xworkflows import models as xwf_models

from itou.approvals.models import Approval, Suspension
from itou.eligibility.models import EligibilityDiagnosis
from itou.utils.emails import get_email_message
from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF


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
    STATE_CANCELLED = "cancelled"
    STATE_OBSOLETE = "obsolete"

    STATE_CHOICES = (
        (STATE_NEW, _("Nouvelle candidature")),
        (STATE_PROCESSING, _("Candidature à l'étude")),
        (STATE_POSTPONED, _("Candidature en liste d'attente")),
        (STATE_ACCEPTED, _("Candidature acceptée")),
        (STATE_REFUSED, _("Candidature déclinée")),
        (STATE_CANCELLED, _("Embauche annulée")),
        (STATE_OBSOLETE, _("Embauché ailleurs")),
    )

    states = STATE_CHOICES

    TRANSITION_PROCESS = "process"
    TRANSITION_POSTPONE = "postpone"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_REFUSE = "refuse"
    TRANSITION_CANCEL = "cancel"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, _("Étudier la candidature")),
        (TRANSITION_POSTPONE, _("Reporter la candidature")),
        (TRANSITION_ACCEPT, _("Accepter la candidature")),
        (TRANSITION_REFUSE, _("Décliner la candidature")),
        (TRANSITION_CANCEL, _("Annuler la candidature")),
        (TRANSITION_RENDER_OBSOLETE, _("Rendre obsolete la candidature")),
    )

    transitions = (
        (TRANSITION_PROCESS, STATE_NEW, STATE_PROCESSING),
        (TRANSITION_POSTPONE, STATE_PROCESSING, STATE_POSTPONED),
        (TRANSITION_ACCEPT, [STATE_PROCESSING, STATE_POSTPONED], STATE_ACCEPTED),
        (TRANSITION_REFUSE, [STATE_PROCESSING, STATE_POSTPONED], STATE_REFUSED),
        (TRANSITION_CANCEL, STATE_ACCEPTED, STATE_CANCELLED),
        (TRANSITION_RENDER_OBSOLETE, [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED], STATE_OBSOLETE),
    )

    initial_state = STATE_NEW

    log_model = "job_applications.JobApplicationTransitionLog"


class JobApplicationQuerySet(models.QuerySet):
    def siae_member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(to_siae__members=user, to_siae__members__is_active=True)

    def pending(self):
        return self.filter(
            state__in=[
                JobApplicationWorkflow.STATE_NEW,
                JobApplicationWorkflow.STATE_PROCESSING,
                JobApplicationWorkflow.STATE_POSTPONED,
            ]
        )

    def accepted(self):
        return self.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    def get_unique_fk_objects(self, fk_field):
        """
        Get unique foreign key objects in a single query.
        TODO: move this method in a custom manager since it's not chainable.
        """
        if fk_field not in ["job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae"]:
            raise RuntimeError("Unauthorized fk_field")

        return [
            getattr(job_application, fk_field)
            for job_application in self.order_by(fk_field).distinct(fk_field).select_related(fk_field)
            if getattr(job_application, fk_field)
        ]

    def created_in_past_hours(self, hours):
        """
        Returns objects created during the specified hours period.
        """
        past_dt = timezone.now() - timezone.timedelta(hours=hours)
        return self.filter(created_at__gte=past_dt)

    def manual_approval_delivery_required(self):
        """
        Returns objects that require a manual PASS IAE delivery.
        """
        return self.filter(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
            approval_number_sent_by_email=False,
            approval_manually_refused_at=None,
        )

    def with_list_related_data(self):
        """
        Stop the deluge of database queries that is caused by accessing related
        objects in job applications's lists.
        """
        qs = self.select_related(
            "approval",
            "job_seeker",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae__convention",
        ).prefetch_related("selected_jobs__appellation")
        has_suspended_approval = Suspension.objects.filter(approval=OuterRef("approval")).in_progress()
        return qs.annotate(has_suspended_approval=Exists(has_suspended_approval))


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    An "unsolicited" job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    SENDER_KIND_JOB_SEEKER = KIND_JOB_SEEKER
    SENDER_KIND_PRESCRIBER = KIND_PRESCRIBER
    SENDER_KIND_SIAE_STAFF = KIND_SIAE_STAFF

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
    REFUSAL_REASON_APPROVAL_EXPIRATION_TOO_CLOSE = "approval_expiration_too_close"
    REFUSAL_REASON_DEACTIVATION = "deactivation"
    REFUSAL_REASON_OTHER = "other"
    REFUSAL_REASON_CHOICES = (
        (REFUSAL_REASON_DID_NOT_COME, _("Candidat non venu ou non joignable")),
        (REFUSAL_REASON_UNAVAILABLE, _("Candidat indisponible ou non intéressé par le poste")),
        (REFUSAL_REASON_NON_ELIGIBLE, _("Candidat non éligible")),
        (
            REFUSAL_REASON_ELIGIBILITY_DOUBT,
            _("Doute sur l'éligibilité du candidat (penser à renvoyer la personne vers un prescripteur)"),
        ),
        (
            REFUSAL_REASON_INCOMPATIBLE,
            _("Un des freins à l'emploi du candidat est incompatible avec le poste proposé"),
        ),
        (
            REFUSAL_REASON_PREVENT_OBJECTIVES,
            _("L'embauche du candidat empêche la réalisation des objectifs du dialogue de gestion"),
        ),
        (REFUSAL_REASON_NO_POSITION, _("Pas de poste ouvert en ce moment")),
        (REFUSAL_REASON_APPROVAL_EXPIRATION_TOO_CLOSE, _("La date de fin du PASS IAE / agrément est trop proche")),
        (REFUSAL_REASON_DEACTIVATION, _("La structure n'est plus conventionnée")),
        (REFUSAL_REASON_OTHER, _("Autre")),
    )

    # SIAE have the possibility to update the hiring date if:
    # - it is before the end date of an approval created for this job application
    # - it is in the future, max. MAX_CONTRACT_POSTPONE_IN_DAYS days from today.
    MAX_CONTRACT_POSTPONE_IN_DAYS = 30

    ERROR_START_IN_PAST = _("Il n'est pas possible d'antidater un contrat. Indiquez une date dans le futur.")
    ERROR_END_IS_BEFORE_START = _("La date de fin du contrat doit être postérieure à la date de début.")
    ERROR_DURATION_TOO_LONG = _(f"La durée du contrat ne peut dépasser {Approval.DEFAULT_APPROVAL_YEARS} ans.")
    ERROR_START_AFTER_APPROVAL_END = _(
        "Attention, le PASS IAE sera expiré lors du début du contrat. Veuillez modifier la date de début."
    )
    ERROR_POSTPONE_TOO_FAR = _(
        f"La date de début du contrat ne peut être repoussée de plus de {MAX_CONTRACT_POSTPONE_IN_DAYS} jours."
    )

    APPROVAL_DELIVERY_MODE_AUTOMATIC = "automatic"
    APPROVAL_DELIVERY_MODE_MANUAL = "manual"

    APPROVAL_DELIVERY_MODE_CHOICES = (
        (APPROVAL_DELIVERY_MODE_AUTOMATIC, _("Automatique")),
        (APPROVAL_DELIVERY_MODE_MANUAL, _("Manuel")),
    )

    CANCELLATION_DAYS_AFTER_HIRING_STARTED = 4

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
    sender_siae = models.ForeignKey(
        "siaes.Siae", verbose_name=_("SIAE émettrice"), null=True, blank=True, on_delete=models.CASCADE
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

    state = xwf_models.StateField(JobApplicationWorkflow, verbose_name=_("État"), db_index=True)

    # Jobs in which the job seeker is interested (optional).
    selected_jobs = models.ManyToManyField(
        "siaes.SiaeJobDescription", verbose_name=_("Métiers recherchés"), blank=True
    )

    message = models.TextField(verbose_name=_("Message de candidature"), blank=True)
    answer = models.TextField(verbose_name=_("Message de réponse"), blank=True)
    refusal_reason = models.CharField(
        verbose_name=_("Motifs de refus"), max_length=30, choices=REFUSAL_REASON_CHOICES, blank=True
    )

    hiring_start_at = models.DateField(verbose_name=_("Date de début du contrat"), blank=True, null=True)
    hiring_end_at = models.DateField(verbose_name=_("Date prévisionnelle de fin du contrat"), blank=True, null=True)

    hiring_without_approval = models.BooleanField(
        default=False, verbose_name=_("L'entreprise choisit de ne pas obtenir un PASS IAE à l'embauche")
    )

    # Job applications sent to SIAEs subject to eligibility rules can obtain an
    # Approval after being accepted.
    approval = models.ForeignKey(
        "approvals.Approval", verbose_name=_("PASS IAE"), null=True, blank=True, on_delete=models.SET_NULL
    )
    approval_delivery_mode = models.CharField(
        verbose_name=_("Mode d'attribution du PASS IAE"),
        max_length=30,
        choices=APPROVAL_DELIVERY_MODE_CHOICES,
        blank=True,
    )
    # Fields used for approvals processed both manually or automatically.
    approval_number_sent_by_email = models.BooleanField(verbose_name=_("PASS IAE envoyé par email"), default=False)
    approval_number_sent_at = models.DateTimeField(
        verbose_name=_("Date d'envoi du PASS IAE"), blank=True, null=True, db_index=True
    )
    # Fields used only for manual processing.
    approval_manually_delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("PASS IAE délivré manuellement par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_manually_delivered",
    )
    approval_manually_refused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("PASS IAE refusé manuellement par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_manually_refused",
    )
    approval_manually_refused_at = models.DateTimeField(
        verbose_name=_("Date de refus manuel du PASS IAE"), blank=True, null=True
    )

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True, db_index=True)

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

    @property
    def is_sent_by_proxy(self):
        return self.sender != self.job_seeker

    @property
    def is_sent_by_authorized_prescriber(self):
        return bool(
            self.sender_kind == self.SENDER_KIND_PRESCRIBER
            and self.sender_prescriber_organization
            and self.sender_prescriber_organization.is_authorized
        )

    @property
    def is_spontaneous(self):
        return self.selected_jobs.exists()

    @property
    def eligibility_diagnosis_by_siae_required(self):
        """
        Returns True if an eligibility diagnosis must be made by an SIAE
        when processing an application, False otherwise.
        """
        return (
            (self.state.is_processing or self.state.is_postponed)
            and self.to_siae.is_subject_to_eligibility_rules
            and not EligibilityDiagnosis.objects.has_considered_valid(self.job_seeker, for_siae=self.to_siae)
        )

    @property
    def manual_approval_delivery_required(self):
        """
        Returns True if the current instance require a manual PASS IAE delivery, False otherwise.
        """
        return (
            self.state.is_accepted
            and self.approval_delivery_mode == self.APPROVAL_DELIVERY_MODE_MANUAL
            and not self.approval_number_sent_by_email
            and self.approval_manually_refused_at is None
        )

    @property
    def accepted_by(self):
        if not self.state.is_accepted:
            return None
        return self.logs.select_related("user").get(to_state=JobApplicationWorkflow.STATE_ACCEPTED).user

    @property
    def can_download_approval_as_pdf(self):
        return (
            self.state.is_accepted
            and not self.can_be_cancelled
            and self.to_siae.is_subject_to_eligibility_rules
            and self.approval
            and self.approval.is_valid
        )

    @property
    def can_be_cancelled(self):
        if self.hiring_start_at:
            today = datetime.date.today()
            delay_ends_at = self.hiring_start_at + relativedelta(days=self.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            return today <= delay_ends_at
        return False

    @property
    def cancellation_delay_end(self):
        return self.hiring_start_at + relativedelta(days=self.CANCELLATION_DAYS_AFTER_HIRING_STARTED)

    @property
    def is_refused_due_to_deactivation(self):
        return (
            self.state == JobApplicationWorkflow.STATE_REFUSED
            and self.refusal_reason == self.REFUSAL_REASON_DEACTIVATION
        )

    @property
    def has_editable_job_seeker(self):
        return (self.state.is_processing or self.state.is_accepted) and self.job_seeker.is_handled_by_proxy

    @property
    def hiring_starts_in_future(self):
        if self.hiring_start_at:
            return datetime.date.today() < self.hiring_start_at
        return False

    @property
    def can_update_hiring_start(self):
        return self.hiring_starts_in_future and self.state in [
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_POSTPONED,
        ]

    # Workflow transitions.

    @xwf_models.transition()
    def process(self, *args, **kwargs):
        pass

    @xwf_models.transition()
    def accept(self, *args, **kwargs):

        accepted_by = kwargs.get("user")

        # Mark other related job applications as obsolete.
        for job_application in self.job_seeker.job_applications.exclude(pk=self.pk).pending():
            job_application.render_obsolete(*args, **kwargs)

        # Notification email.
        emails = [self.email_accept]

        # Approval issuance logic.
        if not self.hiring_without_approval and self.to_siae.is_subject_to_eligibility_rules:

            approvals_wrapper = self.job_seeker.approvals_wrapper

            if approvals_wrapper.has_in_waiting_period and not self.is_sent_by_authorized_prescriber:
                # Security check: it's supposed to be blocked upstream.
                raise xwf_models.AbortTransition("Job seeker has an approval in waiting period.")

            if approvals_wrapper.has_valid:
                # Automatically reuse an existing valid Itou or PE approval.
                self.approval = Approval.get_or_create_from_valid(approvals_wrapper)
                emails.append(self.email_deliver_approval(accepted_by))
            elif (
                self.job_seeker.pole_emploi_id
                or self.job_seeker.lack_of_pole_emploi_id_reason == self.job_seeker.REASON_NOT_REGISTERED
            ):
                # Automatically create a new approval.
                new_approval = Approval(
                    start_at=self.hiring_start_at,
                    end_at=Approval.get_default_end_date(self.hiring_start_at),
                    number=Approval.get_next_number(self.hiring_start_at),
                    user=self.job_seeker,
                )
                new_approval.save()
                self.approval = new_approval
                emails.append(self.email_deliver_approval(accepted_by))
            elif self.job_seeker.lack_of_pole_emploi_id_reason == self.job_seeker.REASON_FORGOTTEN:
                # Trigger a manual approval creation.
                self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_MANUAL
                emails.append(self.email_manual_approval_delivery_required_notification(accepted_by))
            else:
                raise xwf_models.AbortTransition("Job seeker has an invalid PE status, cannot issue approval.")

        # Send emails in batch.
        connection = mail.get_connection()
        connection.send_messages(emails)

        if self.approval:
            self.approval_number_sent_by_email = True
            self.approval_number_sent_at = timezone.now()
            self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_AUTOMATIC

    @xwf_models.transition()
    def refuse(self, *args, **kwargs):
        # Send notification.
        connection = mail.get_connection()
        emails = [self.email_refuse]
        connection.send_messages(emails)

    @xwf_models.transition()
    def cancel(self, *args, **kwargs):
        if not self.can_be_cancelled:
            raise xwf_models.AbortTransition(_("Cette candidature n'a pu être annulée."))

        if self.approval and self.approval.can_be_deleted:
            self.approval.delete()
            self.approval = None

        # Send notification.
        user = kwargs.get("user")
        connection = mail.get_connection()
        emails = [self.email_cancel(cancelled_by=user)]
        connection.send_messages(emails)

    @xwf_models.transition()
    def render_obsolete(self, *args, **kwargs):
        pass

    # Emails.
    @property
    def email_new_for_prescriber(self):
        to = [self.sender.email]
        context = {"job_application": self}
        subject = "apply/email/new_for_prescriber_subject.txt"
        body = "apply/email/new_for_prescriber_body.txt"
        return get_email_message(to, context, subject, body)

    def email_new_for_job_seeker(self, base_url):
        to = [self.job_seeker.email]
        context = {"job_application": self, "base_url": base_url}
        subject = "apply/email/new_for_job_seeker_subject.txt"
        body = "apply/email/new_for_job_seeker_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_accept(self):
        to = [self.job_seeker.email]
        bcc = []
        if self.is_sent_by_proxy:
            bcc.append(self.sender.email)
        context = {"job_application": self, "survey_link": settings.ITOU_EMAIL_PRESCRIBER_NEW_HIRING_URL}
        subject = "apply/email/accept_subject.txt"
        body = "apply/email/accept_body.txt"
        return get_email_message(to, context, subject, body, bcc=bcc)

    @property
    def email_refuse(self):
        to = [self.job_seeker.email]
        bcc = []
        if self.is_sent_by_proxy:
            bcc.append(self.sender.email)
        context = {"job_application": self}
        subject = "apply/email/refuse_subject.txt"
        body = "apply/email/refuse_body.txt"
        return get_email_message(to, context, subject, body, bcc=bcc)

    def email_cancel(self, cancelled_by):
        to = [cancelled_by.email]
        bcc = []
        if self.is_sent_by_proxy:
            bcc.append(self.sender.email)
        context = {"job_application": self}
        subject = "apply/email/cancel_subject.txt"
        body = "apply/email/cancel_body.txt"
        return get_email_message(to, context, subject, body, bcc=bcc)

    def email_deliver_approval(self, accepted_by):
        if not accepted_by:
            raise RuntimeError(_("Unable to determine the recipient email address."))
        if not self.approval:
            raise RuntimeError(_("No approval found for this job application."))
        to = [accepted_by.email]
        context = {"job_application": self, "survey_link": settings.ITOU_EMAIL_APPROVAL_SURVEY_URL}
        subject = "approvals/email/deliver_subject.txt"
        body = "approvals/email/deliver_body.txt"
        return get_email_message(to, context, subject, body)

    def email_manual_approval_delivery_required_notification(self, accepted_by):
        to = [settings.ITOU_EMAIL_CONTACT]
        context = {
            "job_application": self,
            "admin_manually_add_approval_url": reverse(
                "admin:approvals_approval_manually_add_approval", args=[self.pk]
            ),
        }
        if accepted_by:
            context["accepted_by"] = accepted_by
        subject = "approvals/email/manual_delivery_required_notification_subject.txt"
        body = "approvals/email/manual_delivery_required_notification_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_manually_refuse_approval(self):
        if not self.accepted_by:
            raise RuntimeError(_("Unable to determine the recipient email address."))
        to = [self.accepted_by.email]
        context = {"job_application": self}
        subject = "approvals/email/refuse_manually_subject.txt"
        body = "approvals/email/refuse_manually_body.txt"
        return get_email_message(to, context, subject, body)

    def manually_deliver_approval(self, delivered_by):
        """
        Manually deliver an approval.
        """
        email = self.email_deliver_approval(self.accepted_by)
        email.send()
        self.approval_number_sent_by_email = True
        self.approval_number_sent_at = timezone.now()
        self.approval_manually_delivered_by = delivered_by
        self.save()

    def manually_refuse_approval(self, refused_by):
        """
        Manually refuse an approval.
        """
        self.approval_manually_refused_by = refused_by
        self.approval_manually_refused_at = timezone.now()
        self.save()
        email = self.email_manually_refuse_approval
        email.send()


class JobApplicationTransitionLog(xwf_models.BaseTransitionLog):
    """
    JobApplication's transition logs are stored in this table.
    https://django-xworkflows.readthedocs.io/en/latest/internals.html#django_xworkflows.models.BaseTransitionLog
    """

    MODIFIED_OBJECT_FIELD = "job_application"
    EXTRA_LOG_ATTRIBUTES = (("user", "user", None),)
    job_application = models.ForeignKey(JobApplication, related_name="logs", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.SET_NULL)

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
