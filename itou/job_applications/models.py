import datetime
import logging
import uuid
from time import sleep

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.db import models
from django.db.models import BooleanField, Case, Count, Exists, Max, OuterRef, Q, Subquery, When
from django.db.models.functions import Greatest, TruncMonth
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.models import Approval, Suspension
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.tasks import huey_notify_pole_employ
from itou.utils.apis.esd import get_access_token
from itou.utils.apis.pole_emploi import (
    POLE_EMPLOI_PASS_APPROVED,
    PoleEmploiIndividu,
    PoleEmploiMiseAJourPassIAEException,
    mise_a_jour_pass_iae,
    recherche_individu_certifie_api,
)
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
    # When a job application is accepted, all other job seeker's pending applications become obsolete.
    STATE_OBSOLETE = "obsolete"

    STATE_CHOICES = (
        (STATE_NEW, "Nouvelle candidature"),
        (STATE_PROCESSING, "Candidature à l'étude"),
        (STATE_POSTPONED, "Candidature en liste d'attente"),
        (STATE_ACCEPTED, "Candidature acceptée"),
        (STATE_REFUSED, "Candidature déclinée"),
        (STATE_CANCELLED, "Embauche annulée"),
        (STATE_OBSOLETE, "Embauché ailleurs"),
    )

    states = STATE_CHOICES

    TRANSITION_PROCESS = "process"
    TRANSITION_POSTPONE = "postpone"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_REFUSE = "refuse"
    TRANSITION_CANCEL = "cancel"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, "Étudier la candidature"),
        (TRANSITION_POSTPONE, "Reporter la candidature"),
        (TRANSITION_ACCEPT, "Accepter la candidature"),
        (TRANSITION_REFUSE, "Décliner la candidature"),
        (TRANSITION_CANCEL, "Annuler la candidature"),
        (TRANSITION_RENDER_OBSOLETE, "Rendre obsolete la candidature"),
    )

    CAN_BE_ACCEPTED_STATES = [STATE_PROCESSING, STATE_POSTPONED, STATE_OBSOLETE, STATE_REFUSED, STATE_CANCELLED]

    transitions = (
        (TRANSITION_PROCESS, STATE_NEW, STATE_PROCESSING),
        (TRANSITION_POSTPONE, STATE_PROCESSING, STATE_POSTPONED),
        (TRANSITION_ACCEPT, CAN_BE_ACCEPTED_STATES, STATE_ACCEPTED),
        (TRANSITION_REFUSE, [STATE_PROCESSING, STATE_POSTPONED], STATE_REFUSED),
        (TRANSITION_CANCEL, STATE_ACCEPTED, STATE_CANCELLED),
        (TRANSITION_RENDER_OBSOLETE, [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED], STATE_OBSOLETE),
    )

    PENDING_STATES = [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED]
    initial_state = STATE_NEW

    log_model = "job_applications.JobApplicationTransitionLog"


class JobApplicationQuerySet(models.QuerySet):
    def siae_member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(to_siae__members=user, to_siae__members__is_active=True)

    def pending(self):
        return self.filter(state__in=JobApplicationWorkflow.PENDING_STATES)

    def accepted(self):
        return self.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    def not_archived(self):
        """
        Filters out the archived job_applications
        """
        return self.exclude(hidden_for_siae=True)

    def created_on_given_year_and_month(self, year, month):
        return self.filter(created_at__year=year, created_at__month=month)

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

    def created_in_past(self, seconds=0, minutes=0, hours=0):
        """
        Returns objects created during the specified time period.
        """
        past_dt = timezone.now() - timezone.timedelta(seconds=seconds, minutes=minutes, hours=hours)
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

    def with_has_suspended_approval(self):
        has_suspended_approval = Suspension.objects.filter(approval=OuterRef("approval")).in_progress()
        return self.annotate(has_suspended_approval=Exists(has_suspended_approval))

    def with_last_change(self):
        return self.annotate(last_change=Greatest("created_at", Max("logs__timestamp")))

    def with_is_pending_for_too_long(self):
        freshness_limit = timezone.now() - relativedelta(weeks=self.model.WEEKS_BEFORE_CONSIDERED_OLD)
        pending_states = JobApplicationWorkflow.PENDING_STATES
        return self.with_last_change().annotate(
            is_pending_for_too_long=Case(
                When(last_change__lt=freshness_limit, state__in=pending_states, then=True),
                default=False,
                output_field=BooleanField(),
            )
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

        # Many job applications from AI exports share the exact same `created_at` value thus we secondarily order
        # by pk to prevent flakyness in the resulting pagination (a same job application appearing both on page 1
        # and page 2). Note that pk is a hash and not the usual incrementing integer, thus ordering by it does not
        # make any other sense than being deterministic for pagination purposes.
        return qs.with_has_suspended_approval().with_is_pending_for_too_long().order_by("-created_at", "pk")

    def with_monthly_counts(self):
        """
        Takes a list of job_applications, and returns a list of
        pairs (month, amount of job applications in this month)
        sorted by month
        """
        return (
            self.annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(c=Count("id"))
            .values("month", "c")
            .order_by("-month")
        )

    def eligible_as_employee_record(self, siae):
        """
        List job applications that will have to be transfered to ASP
        via the employee record app.

        These job applications must:
        - be definitely accepted
        - have no one-to-one relationship with an employee record
        - have been created after production date

        An eligible job application *may* or *may not* have an employee record object linked
        to it.

        For instance, when creating a new employee record from an eligible job application
        and NOT finishing the entire creation process.
        (employee record object creation occurs half-way of the "tunnel")
        """

        # Exclude existing employee records with same approval and asp_id
        # Rule: you can only create *one* employee record for a given asp_id / approval pair
        subquery = Subquery(
            self.exclude(to_siae=siae).filter(
                employee_record__asp_id=siae.asp_id,
                employee_record__approval_number=OuterRef("approval__number"),
            )
        )

        return (
            # Job application without approval are out of scope
            self.exclude(approval=None)
            # Prevent employee records creation (batch import for example).
            .filter(create_employee_record=True)
            # See `subquery` above : exclude possible ASP duplicates
            .exclude(Exists(subquery))
            # Only ACCEPTED job applications can be transformed into employee records
            .accepted()
            # Accept only job applications without linked or processed employee record
            .filter(Q(employee_record__status="NEW") | Q(employee_record__isnull=True))
            .filter(
                # Only for current SIAE
                to_siae=siae,
                # Hiring must start after production date:
                hiring_start_at__gte=settings.EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
            )
            .select_related("job_seeker", "approval")
            .order_by("-hiring_start_at")
        )


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    A job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    SENDER_KIND_JOB_SEEKER = KIND_JOB_SEEKER
    SENDER_KIND_PRESCRIBER = KIND_PRESCRIBER
    SENDER_KIND_SIAE_STAFF = KIND_SIAE_STAFF

    SENDER_KIND_CHOICES = (
        (SENDER_KIND_JOB_SEEKER, "Demandeur d'emploi"),
        (SENDER_KIND_PRESCRIBER, "Prescripteur"),
        (SENDER_KIND_SIAE_STAFF, "Employeur (SIAE)"),
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
    REFUSAL_REASON_NOT_MOBILE = "not_mobile"
    REFUSAL_REASON_POORLY_INFORMED = "poorly_informed"
    REFUSAL_REASON_OTHER = "other"
    REFUSAL_REASON_CHOICES = (
        (REFUSAL_REASON_DID_NOT_COME, "Candidat non venu ou non joignable"),
        (REFUSAL_REASON_UNAVAILABLE, "Candidat indisponible ou non intéressé par le poste"),
        (REFUSAL_REASON_NON_ELIGIBLE, "Candidat non éligible"),
        (REFUSAL_REASON_NOT_MOBILE, "Candidat non mobile"),
        (
            REFUSAL_REASON_ELIGIBILITY_DOUBT,
            "Doute sur l'éligibilité du candidat (penser à renvoyer la personne vers un prescripteur)",
        ),
        (
            REFUSAL_REASON_INCOMPATIBLE,
            "Un des freins à l'emploi du candidat est incompatible avec le poste proposé",
        ),
        (
            REFUSAL_REASON_PREVENT_OBJECTIVES,
            "L'embauche du candidat empêche la réalisation des objectifs du dialogue de gestion",
        ),
        (REFUSAL_REASON_NO_POSITION, "Pas de poste ouvert en ce moment"),
        (REFUSAL_REASON_APPROVAL_EXPIRATION_TOO_CLOSE, "La date de fin du PASS IAE / agrément est trop proche"),
        (REFUSAL_REASON_DEACTIVATION, "La structure n'est plus conventionnée"),
        (REFUSAL_REASON_POORLY_INFORMED, "Candidature pas assez renseignée"),
        (REFUSAL_REASON_OTHER, "Autre"),
    )

    # SIAE have the possibility to update the hiring date if:
    # - it is before the end date of an approval created for this job application
    # - it is in the future, max. MAX_CONTRACT_POSTPONE_IN_DAYS days from today.
    MAX_CONTRACT_POSTPONE_IN_DAYS = 30

    ERROR_START_IN_PAST = "Il n'est pas possible d'antidater un contrat. Indiquez une date dans le futur."
    ERROR_END_IS_BEFORE_START = "La date de fin du contrat doit être postérieure à la date de début."
    ERROR_START_AFTER_APPROVAL_END = (
        "Attention, le PASS IAE sera expiré lors du début du contrat. Veuillez modifier la date de début."
    )
    ERROR_POSTPONE_TOO_FAR = (
        f"La date de début du contrat ne peut être repoussée de plus de {MAX_CONTRACT_POSTPONE_IN_DAYS} jours."
    )

    APPROVAL_DELIVERY_MODE_AUTOMATIC = "automatic"
    APPROVAL_DELIVERY_MODE_MANUAL = "manual"

    APPROVAL_DELIVERY_MODE_CHOICES = (
        (APPROVAL_DELIVERY_MODE_AUTOMATIC, "Automatique"),
        (APPROVAL_DELIVERY_MODE_MANUAL, "Manuel"),
    )

    WEEKS_BEFORE_CONSIDERED_OLD = 3

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="job_applications",
    )

    # The job seeker's eligibility diagnosis used for this job application
    # (required for SIAEs subject to eligibility rules).
    # It is already linked to the job seeker but this double link is added
    # to easily find out which one was used for a given job application.
    # Use `self.get_eligibility_diagnosis()` to handle business rules.
    eligibility_diagnosis = models.ForeignKey(
        "eligibility.EligibilityDiagnosis",
        verbose_name="Diagnostic d'éligibilité",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Exclude flagged approvals (batch creation or import of approvals).
    # See itou.users.management.commands.import_ai_employees.
    create_employee_record = models.BooleanField(default=True, verbose_name="Création d'une fiche salarié")

    # The job seeker's resume used for this job application.
    resume_link = models.URLField(max_length=500, verbose_name="Lien vers un CV", blank=True)

    # Who send the job application. It can be the same user as `job_seeker`
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Émetteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_applications_sent",
    )

    sender_kind = models.CharField(
        verbose_name="Type de l'émetteur",
        max_length=10,
        choices=SENDER_KIND_CHOICES,
        default=SENDER_KIND_PRESCRIBER,
    )

    # When the sender is an SIAE staff member, keep a track of his current SIAE.
    sender_siae = models.ForeignKey(
        "siaes.Siae", verbose_name="SIAE émettrice", null=True, blank=True, on_delete=models.CASCADE
    )

    # When the sender is a prescriber, keep a track of his current organization (if any).
    sender_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="Organisation du prescripteur émettrice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    to_siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name="SIAE destinataire",
        on_delete=models.CASCADE,
        related_name="job_applications_received",
    )

    state = xwf_models.StateField(JobApplicationWorkflow, verbose_name="État", db_index=True)

    # Jobs in which the job seeker is interested (optional).
    selected_jobs = models.ManyToManyField("siaes.SiaeJobDescription", verbose_name="Métiers recherchés", blank=True)

    message = models.TextField(verbose_name="Message de candidature", blank=True)
    answer = models.TextField(verbose_name="Message de réponse", blank=True)
    answer_to_prescriber = models.TextField(verbose_name="Message de réponse au prescripeur", blank=True)
    refusal_reason = models.CharField(
        verbose_name="Motifs de refus", max_length=30, choices=REFUSAL_REASON_CHOICES, blank=True
    )

    hiring_start_at = models.DateField(verbose_name="Date de début du contrat", blank=True, null=True, db_index=True)
    hiring_end_at = models.DateField(verbose_name="Date prévisionnelle de fin du contrat", blank=True, null=True)

    hiring_without_approval = models.BooleanField(
        default=False, verbose_name="L'entreprise choisit de ne pas obtenir un PASS IAE à l'embauche"
    )

    # This flag is used in the `PoleEmploiApproval`'s conversion process.
    # This process is required following the end of the software allowing Pôle emploi to manage their approvals.
    # The process allows to convert a `PoleEmploiApproval` into an `Approval`.
    created_from_pe_approval = models.BooleanField(
        default=False, verbose_name="Candidature créée lors de l'import d'un agrément Pole Emploi"
    )

    # Job applications sent to SIAEs subject to eligibility rules can obtain an
    # Approval after being accepted.
    approval = models.ForeignKey(
        "approvals.Approval", verbose_name="PASS IAE", null=True, blank=True, on_delete=models.SET_NULL
    )
    approval_delivery_mode = models.CharField(
        verbose_name="Mode d'attribution du PASS IAE",
        max_length=30,
        choices=APPROVAL_DELIVERY_MODE_CHOICES,
        blank=True,
    )
    # Fields used for approvals processed both manually or automatically.
    approval_number_sent_by_email = models.BooleanField(verbose_name="PASS IAE envoyé par email", default=False)
    approval_number_sent_at = models.DateTimeField(
        verbose_name="Date d'envoi du PASS IAE", blank=True, null=True, db_index=True
    )
    # Fields used only for manual processing.
    approval_manually_delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="PASS IAE délivré manuellement par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_manually_delivered",
    )
    approval_manually_refused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="PASS IAE refusé manuellement par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_manually_refused",
    )
    approval_manually_refused_at = models.DateTimeField(
        verbose_name="Date de refus manuel du PASS IAE", blank=True, null=True
    )

    hidden_for_siae = models.BooleanField(default=False, verbose_name="Masqué coté employeur")

    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True, db_index=True)

    objects = models.Manager.from_queryset(JobApplicationQuerySet)()

    class Meta:
        verbose_name = "Candidature"
        verbose_name_plural = "Candidatures"
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def is_pending(self):
        return self.state in JobApplicationWorkflow.PENDING_STATES

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
        return not self.selected_jobs.exists()

    @property
    def eligibility_diagnosis_by_siae_required(self):
        """
        Returns True if an eligibility diagnosis must be made by an SIAE
        when processing an application, False otherwise.
        """
        return (
            (self.state in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES)
            and self.to_siae.is_subject_to_eligibility_rules
            and not self.job_seeker.has_valid_diagnosis(for_siae=self.to_siae)
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
        return self.logs.select_related("user").filter(to_state=JobApplicationWorkflow.STATE_ACCEPTED).last().user

    @property
    def can_download_approval_as_pdf(self):
        return self.state.is_accepted and self.to_siae.is_subject_to_eligibility_rules and self.approval

    @property
    def can_be_cancelled(self):
        if self.is_from_ai_stock:
            return False
        if self.hiring_start_at:
            # A job application can be canceled provided that
            # there is no employee record linked with a status:
            # - SENT
            # - ACCEPTED
            # (likely to be accepted or already accepted by ASP)
            employee_record = self.employee_record.first()
            blocked = employee_record and employee_record.is_blocking_job_application_cancellation
            return not blocked
        return False

    @property
    def can_be_archived(self):
        return self.state in [
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

    @property
    def is_refused_due_to_deactivation(self):
        return (
            self.state == JobApplicationWorkflow.STATE_REFUSED
            and self.refusal_reason == self.REFUSAL_REASON_DEACTIVATION
        )

    @property
    def is_from_ai_stock(self):
        """On November 30th, 2021, we created job applications to deliver approvals.
        See itou.users.management.commands.import_ai_employees.
        """
        # Avoid a circular import.
        user_manager = self.job_seeker._meta.model.objects
        developer_qs = user_manager.filter(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        if not developer_qs:
            return False
        developer = developer_qs.first()
        return (
            self.approval_manually_delivered_by == developer
            and self.created_at.date() == settings.AI_EMPLOYEES_STOCK_IMPORT_DATE.date()
        )

    @property
    def has_editable_job_seeker(self):
        return (
            self.state.is_new or self.state.is_processing or self.state.is_accepted
        ) and self.job_seeker.is_handled_by_proxy

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

    @property
    def display_sender_kind(self):
        """
        Converts itou internal prescriber kinds into something readable
        """
        kind = "Candidature spontanée"
        if self.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
            kind = "Auto-prescription"
        elif self.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
            kind = "Orienteur"
            if self.is_sent_by_authorized_prescriber:
                kind = "Prescripteur habilité"
        return kind

    @property
    def can_have_employee_record(self):
        """
        Check if EmployeeRecord does not exit and can be created for this JobApplication
        """
        is_application_valid = (
            self.hiring_start_at >= settings.EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date()
            and not self.hiring_without_approval
            and self.state == JobApplicationWorkflow.STATE_ACCEPTED
            and self.approval.is_valid()
        )

        return is_application_valid and not self.employee_record.first() and self.to_siae.can_use_employee_record

    def get_eligibility_diagnosis(self):
        """
        Returns the eligibility diagnosis linked to this job application or None.
        """
        if not self.to_siae.is_subject_to_eligibility_rules:
            return None
        if self.eligibility_diagnosis:
            return self.eligibility_diagnosis
        # As long as the job application has not been accepted, diagnosis-related
        # business rules may still prioritize one diagnosis over another.
        return EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, for_siae=self.to_siae)

    def get_resume_link(self):
        if self.resume_link:
            return self.resume_link
        elif self.job_seeker.resume_link:
            return self.job_seeker.resume_link
        return None

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

        # Notification emails.
        emails = [self.email_accept_for_job_seeker]
        if self.is_sent_by_proxy:
            emails.append(self.email_accept_for_proxy)

        # Approval issuance logic.
        if not self.hiring_without_approval and self.to_siae.is_subject_to_eligibility_rules:

            approvals_wrapper = self.job_seeker.approvals_wrapper

            if approvals_wrapper.has_in_waiting_period:
                if approvals_wrapper.cannot_bypass_waiting_period(
                    siae=self.to_siae, sender_prescriber_organization=self.sender_prescriber_organization
                ):
                    # Security check: it's supposed to be blocked upstream.
                    raise xwf_models.AbortTransition("Job seeker has an approval in waiting period.")

            if approvals_wrapper.has_valid:
                # Automatically reuse an existing valid Itou or PE approval.
                self.approval = Approval.get_or_create_from_valid(approvals_wrapper)
                if self.approval.start_at > self.hiring_start_at:
                    # As a job seeker can have multiple contracts at the same time,
                    # the approval should start at the same time as most recent contract.
                    self.approval.update_start_date(new_start_date=self.hiring_start_at)
                emails.append(self.email_deliver_approval(accepted_by))
            elif (
                self.job_seeker.pole_emploi_id
                or self.job_seeker.lack_of_pole_emploi_id_reason == self.job_seeker.REASON_NOT_REGISTERED
            ):
                # Automatically create a new approval.
                new_approval = Approval(
                    start_at=self.hiring_start_at,
                    end_at=Approval.get_default_end_date(self.hiring_start_at),
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

        # Link to the job seeker's eligibility diagnosis.
        if self.to_siae.is_subject_to_eligibility_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, for_siae=self.to_siae
            )

        # Send emails in batch.
        connection = mail.get_connection()
        connection.send_messages(emails)

        if self.approval:
            self.approval_number_sent_by_email = True
            self.approval_number_sent_at = timezone.now()
            self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_AUTOMATIC
            self.approval.unsuspend(self.hiring_start_at)
            self.notify_pole_emploi_accepted()

    @xwf_models.transition()
    def refuse(self, *args, **kwargs):
        # Send notification.
        connection = mail.get_connection()
        emails = [self.email_refuse_for_job_seeker]
        if self.is_sent_by_proxy:
            emails.append(self.email_refuse_for_proxy)
        connection.send_messages(emails)

    @xwf_models.transition()
    def cancel(self, *args, **kwargs):
        if not self.can_be_cancelled:
            raise xwf_models.AbortTransition("Cette candidature n'a pu être annulée.")

        if self.approval and self.approval.can_be_deleted:
            self.approval.delete()
            self.approval = None

            # Remove flags on the job application about approval
            self.approval_number_sent_by_email = False
            self.approval_number_sent_at = None
            self.approval_delivery_mode = ""
            self.approval_manually_delivered_by = None

        # Delete matching employee record, if any
        employee_record = self.employee_record.first()
        if employee_record:
            employee_record.delete()

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
    def email_accept_for_job_seeker(self):
        to = [self.job_seeker.email]
        context = {"job_application": self}
        subject = "apply/email/accept_for_job_seeker_subject.txt"
        body = "apply/email/accept_for_job_seeker_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_accept_for_proxy(self):
        if not self.is_sent_by_proxy:
            raise RuntimeError("The job application was not sent by a proxy.")
        to = [self.sender.email]
        context = {"job_application": self}
        if self.sender_prescriber_organization:
            # Include the survey link for all prescribers's organizations.
            context["prescriber_survey_link"] = self.sender_prescriber_organization.accept_survey_url
        subject = "apply/email/accept_for_proxy_subject.txt"
        body = "apply/email/accept_for_proxy_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_refuse_for_proxy(self):
        to = [self.sender.email]
        context = {"job_application": self}
        subject = "apply/email/refuse_subject.txt"
        body = "apply/email/refuse_body_for_proxy.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_refuse_for_job_seeker(self):
        to = [self.job_seeker.email]
        context = {"job_application": self}
        subject = "apply/email/refuse_subject.txt"
        body = "apply/email/refuse_body_for_job_seeker.txt"
        return get_email_message(to, context, subject, body)

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
            raise RuntimeError("Unable to determine the recipient email address.")
        if not self.approval:
            raise RuntimeError("No approval found for this job application.")
        to = [accepted_by.email]
        context = {"job_application": self, "siae_survey_link": self.to_siae.accept_survey_url}
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
            raise RuntimeError("Unable to determine the recipient email address.")
        to = [self.accepted_by.email]
        context = {"job_application": self}
        subject = "approvals/email/refuse_manually_subject.txt"
        body = "approvals/email/refuse_manually_body.txt"
        return get_email_message(to, context, subject, body)

    def manually_deliver_approval(self, delivered_by):
        """
        Manually deliver an approval.
        """
        self.approval_number_sent_by_email = True
        self.approval_number_sent_at = timezone.now()
        self.approval_manually_delivered_by = delivered_by
        self.save()
        # Send email at the end because we can't rollback this operation
        email = self.email_deliver_approval(self.accepted_by)
        email.send()

    def manually_refuse_approval(self, refused_by):
        """
        Manually refuse an approval.
        """
        self.approval_manually_refused_by = refused_by
        self.approval_manually_refused_at = timezone.now()
        self.save()
        # Send email at the end because we can't rollback this operation
        email = self.email_manually_refuse_approval
        email.send()

    def notify_pole_emploi_accepted(self) -> bool:
        if settings.API_ESD_SHOULD_PERFORM_MISE_A_JOUR_PASS:
            return huey_notify_pole_employ(self, POLE_EMPLOI_PASS_APPROVED)
        return False

    def _notify_pole_employ(self, mode: str) -> bool:
        """
        The entire logic for notifying Pole Emploi when a job_application is accepted:
            - first, we authenticate to pole-emploi.io with the proper credentials, scopes, environment and
            dry-run/wet run settings
            - then, we search for the job_seeker on their backend. They reply with an encrypted NIR.
            - finally, we use the encrypted NIR to notify them that a job application was accepted or refused.
            We provide what we have about this job application.

        This is VERY error prone and can break in a lot of places. PE’s servers can be down, we may not find
        the job_seeker, the update may fail for various reasons. The rate limiting is low, hence…
        those terrible `sleep` for lack of a better idea for now.

        In order to ensure the rest of the application process will behave properly no matter what happens here:
         - there is a lot of broad exception catching
         - we keep logs of the successful/failed attempts
         - when anything break, we quit early
        """
        # We do not send approvals that start in the future to PE, because the information system in front
        # can’t handle them. I’ll keep my opinion about this for talks that involve an unreasonnable amount of beer.
        # Another mechanism will be in charge of sending them on their start date
        if self.approval.start_at > timezone.now().date():
            return False
        individual = PoleEmploiIndividu.from_job_seeker(self.job_seeker)
        if individual is None or not individual.is_valid():
            # We may not have a valid user (missing NIR, for instance),
            # in which case we can bypass this process entirely
            return False
        log = JobApplicationPoleEmploiNotificationLog(
            job_application=self, status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
        )
        # Step 1: we get the API token
        try:
            token = JobApplicationPoleEmploiNotificationLog.get_token()
            sleep(1)
        except Exception as e:
            log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_AUTHENTICATION
            log.details = str(e)
            log.save()
            return False
        # Step 2 : we fetch the encrypted NIR
        try:
            encrypted_nir = JobApplicationPoleEmploiNotificationLog.get_encrypted_nir_from_individual(
                individual, token
            )
            # 3 requests/second max. I had timeout issues so 1 second takes some margins
            sleep(1)
        except PoleEmploiMiseAJourPassIAEException as e:
            log = JobApplicationPoleEmploiNotificationLog(
                job_application=self,
                status=JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_SEARCH_INDIVIDUAL,
                details=f"{e.http_code} {e.response_code}",
            )
            log.save()
            return False
        # Step 3: we finally notify Pole Emploi that something happened for this user
        try:
            mise_a_jour_pass_iae(self, mode, encrypted_nir, token)
            sleep(1)
        except PoleEmploiMiseAJourPassIAEException as e:
            log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_NOTIFY_POLE_EMPLOI
            log.details = f"{e.http_code} {e.response_code}"
            log.save()
            return False

        log.save()
        return True


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
        verbose_name = "Log des transitions de la candidature"
        verbose_name_plural = "Log des transitions des candidatures"
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.id)

    @property
    def pretty_to_state(self):
        choices = dict(JobApplicationWorkflow.STATE_CHOICES)
        return choices[self.to_state]


class JobApplicationPoleEmploiNotificationLog(models.Model):
    """
    A log used to store what happens when we notify pole emploi
    that a JobApplication has been accepted or refused
    """

    STATUS_OK = "ok"
    STATUS_FAIL_AUTHENTICATION = "authentication_failure"
    STATUS_FAIL_SEARCH_INDIVIDUAL = "search individual failure"
    STATUS_FAIL_NOTIFY_POLE_EMPLOI = "update failure"
    STATUS_TECHNICAL_FAILURE = "technical_failure"

    STATUS_CHOICES = (
        (STATUS_OK, "La mise à jour a abouti"),
        (STATUS_FAIL_AUTHENTICATION, "Mise à jour échouée suite à l’échec d’authentifications aux API pôle emploi"),
        (STATUS_FAIL_SEARCH_INDIVIDUAL, "Mise à jour échouée car candidat non trouvé chez Pôle Emploi"),
        (STATUS_FAIL_NOTIFY_POLE_EMPLOI, "Mise à jour échouée car installation du pass chez pole emploi refusée"),
        (STATUS_TECHNICAL_FAILURE, "Mise à jour échouée suite à un problème technique"),
    )

    status = models.CharField(verbose_name="Motifs d’erreurs", max_length=30, choices=STATUS_CHOICES, blank=True)
    details = models.TextField(verbose_name="Précisions concernant le comportement obtenu", blank=True)

    job_application = models.ForeignKey(
        "job_applications.JobApplication", verbose_name="Candidature", null=True, blank=True, on_delete=models.SET_NULL
    )

    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = "Log des notifications PoleEmploi"
        verbose_name_plural = "Logs des notifications PoleEmploi"
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    API_DATE_FORMAT = "%Y-%m-%d"

    @staticmethod
    def get_token() -> str:
        """returns the necessary token for Updating PoleEmploi, or raise exceptions"""
        maj_pass_iae_api_scope = "passIAE api_maj-pass-iaev1"
        # The sandbox mode involves a slightly different scope
        if settings.API_ESD_MISE_A_JOUR_PASS_MODE != "production":
            maj_pass_iae_api_scope = "passIAE api_testmaj-pass-iaev1"
        # It is not obvious but we can ask for one token only with all the necessary rights
        token_recherche_et_maj = get_access_token(
            f"api_rechercheindividucertifiev1 rechercherIndividuCertifie {maj_pass_iae_api_scope}"
        )
        return token_recherche_et_maj

    @staticmethod
    def get_encrypted_nir_from_individual(individual: PoleEmploiIndividu, api_token: str) -> str:
        individual_pole_emploi_result = recherche_individu_certifie_api(individual, api_token)
        if individual is not None and individual_pole_emploi_result.is_valid:
            return individual_pole_emploi_result.id_national_demandeur
        else:
            return ""
