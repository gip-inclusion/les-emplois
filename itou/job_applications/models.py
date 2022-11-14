import datetime
import logging
import uuid

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import BooleanField, Case, Count, Exists, F, Max, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce, Greatest, TruncMonth
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.models import Approval, Prolongation, Suspension
from itou.eligibility.models import EligibilityDiagnosis, SelectedAdministrativeCriteria
from itou.employee_record import enums as employeerecord_enums
from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.enums import RefusalReason, SenderKind
from itou.job_applications.tasks import huey_notify_pole_emploi
from itou.siaes.models import Siae
from itou.utils.emails import get_email_message, send_email_messages
from itou.utils.urls import get_absolute_url


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
    TRANSITION_TRANSFER = "transfer"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, "Étudier la candidature"),
        (TRANSITION_POSTPONE, "Reporter la candidature"),
        (TRANSITION_ACCEPT, "Accepter la candidature"),
        (TRANSITION_REFUSE, "Décliner la candidature"),
        (TRANSITION_CANCEL, "Annuler la candidature"),
        (TRANSITION_RENDER_OBSOLETE, "Rendre obsolete la candidature"),
        (TRANSITION_TRANSFER, "Transfert de la candidature vers une autre SIAE"),
    )

    CAN_BE_ACCEPTED_STATES = [STATE_PROCESSING, STATE_POSTPONED, STATE_OBSOLETE, STATE_REFUSED, STATE_CANCELLED]
    CAN_BE_TRANSFERRED_STATES = CAN_BE_ACCEPTED_STATES

    transitions = (
        (TRANSITION_PROCESS, STATE_NEW, STATE_PROCESSING),
        (TRANSITION_POSTPONE, STATE_PROCESSING, STATE_POSTPONED),
        (TRANSITION_ACCEPT, CAN_BE_ACCEPTED_STATES, STATE_ACCEPTED),
        (TRANSITION_REFUSE, [STATE_PROCESSING, STATE_POSTPONED], STATE_REFUSED),
        (TRANSITION_CANCEL, STATE_ACCEPTED, STATE_CANCELLED),
        (TRANSITION_RENDER_OBSOLETE, [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED], STATE_OBSOLETE),
        (TRANSITION_TRANSFER, CAN_BE_TRANSFERRED_STATES, STATE_NEW),
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
        if fk_field not in [
            "job_seeker",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae",
        ]:
            raise RuntimeError("Unauthorized fk_field")

        job_applications = self.order_by(fk_field).distinct(fk_field).select_related(fk_field)
        return [
            getattr(job_application, fk_field)
            for job_application in job_applications
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

    def with_accepted_at(self):
        created_at_from_transition = Subquery(
            JobApplicationTransitionLog.objects.filter(
                job_application=OuterRef("pk"),
                transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
            )
            .order_by("-timestamp")
            .values("timestamp")[0:1],
        )
        return self.annotate(
            accepted_at=Case(
                When(created_from_pe_approval=True, then=F("created_at")),
                # A job_application created at the accepted status, still accepted
                When(
                    created_from_pe_approval=False,
                    state=JobApplicationWorkflow.STATE_ACCEPTED,
                    logs__isnull=True,
                    then=F("created_at"),
                ),
                When(created_from_pe_approval=False, then=created_at_from_transition),
            )
        )

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

    def with_last_jobseeker_eligibility_diagnosis(self):
        """
        Gives the last eligibility diagnosis for jobseeker because the "eligibility_diagnosis"
        on `job_applications` model is rarely present.
        """
        sub_query = Subquery(
            (
                EligibilityDiagnosis.objects.filter(job_seeker=OuterRef("job_seeker"))
                .order_by("-created_at")
                .values("id")[:1]
            ),
            output_field=models.IntegerField(),
        )
        return self.annotate(last_jobseeker_eligibility_diagnosis=Coalesce(sub_query, None))

    def with_last_eligibility_diagnosis_criterion(self, criterion):
        """
        Create an annotation by criterion given (used in the filters form).
        The criterion parameter must be the primary key of an AdministrativeCriteria.
        """
        subquery = SelectedAdministrativeCriteria.objects.filter(
            eligibility_diagnosis=OuterRef("last_jobseeker_eligibility_diagnosis"), administrative_criteria=criterion
        )
        return self.annotate(**{f"last_eligibility_diagnosis_criterion_{criterion}": Exists(subquery)})

    def with_list_related_data(self, criteria=None):
        """
        Stop the deluge of database queries that is caused by accessing related
        objects in job applications's lists.
        """
        if criteria is None:
            criteria = []

        qs = self.select_related(
            "approval",
            "job_seeker",
            "sender",
            "sender_siae",
            "sender_prescriber_organization",
            "to_siae__convention",
        ).prefetch_related("selected_jobs__appellation")

        qs = (
            qs.with_has_suspended_approval().with_is_pending_for_too_long().with_last_jobseeker_eligibility_diagnosis()
        )

        # Adding an annotation by selected criterion
        for criterion in criteria:
            # The criterion given to this method is a primary key of an AdministrativeCriteria
            qs = qs.with_last_eligibility_diagnosis_criterion(int(criterion))

        # Many job applications from AI exports share the exact same `created_at` value thus we secondarily order
        # by pk to prevent flakyness in the resulting pagination (a same job application appearing both on page 1
        # and page 2). Note that pk is a hash and not the usual incrementing integer, thus ordering by it does not
        # make any other sense than being deterministic for pagination purposes.
        return qs.order_by("-created_at", "pk")

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

    # Employee record querysets

    def _eligible_job_applications_with_employee_record(self, siae):
        """
        Eligible job applications for employee record query: part 1

        Eligible job applications linked to an employee record,
        provided that the employee record linked to these job applications:
            - has the same ASP_ID of hiring structure,
            - has the same approval,
            - is in `NEW` state.

        Otherwise, these employee records will be rejected by ASP as duplicates.

        Not a public API: use `eligible_as_employee_record`.
        """
        return self.filter(
            to_siae=siae,
            employee_record__status=employeerecord_enums.Status.NEW,
            employee_record__asp_id=F("to_siae__convention__asp_id"),
            employee_record__approval_number=F("approval__number"),
        )

    def _eligible_job_applications_without_employee_record(self, siae):
        """
        Eligible job applications for employee record query: part 2

        Eligible job applications WITHOUT any employee record linked.

        See `eligible_as_employee_record` method for an explanation of business and technical rules.

        Not a public API: use `eligible_as_employee_record`.
        """
        return self.accepted().filter(
            # Must be linked to an approval
            approval__isnull=False,
            # Only for that SIAE
            to_siae=siae,
            # Hiring structure must be one of those kinds
            # FIXME(rsebille): should probably not be handled as SQL because we already have `siae`
            to_siae__kind__in=Siae.ASP_EMPLOYEE_RECORD_KINDS,
            # Admin control: can prevent creation of employee record
            create_employee_record=True,
            # There must be **NO** employee record linked in this part
            employee_record__isnull=True,
            # No employee record is available before this date
            hiring_start_at__gte=EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
        )

    def _eligible_job_applications_with_a_suspended_or_extended_approval(self, siae):
        return (
            self.accepted()
            .annotate(
                has_recent_suspension=Exists(
                    Suspension.objects.filter(
                        siae=OuterRef("to_siae"),
                        approval=OuterRef("approval"),
                        # Limit to recent suspension as the older ones will already have been handled by the support.
                        # The date was chosen arbitrarily, don't mind it too much :).
                        created_at__gte=timezone.make_aware(datetime.datetime(2022, 1, 1)),
                    )
                ),
                has_recent_prolongation=Exists(
                    Prolongation.objects.filter(
                        declared_by_siae=OuterRef("to_siae"),
                        approval=OuterRef("approval"),
                        # Limit to recent prolongation as the older ones will already have been handled by the support.
                        # The date was chosen arbitrarily, don't mind it too much :).
                        created_at__gte=timezone.make_aware(datetime.datetime(2022, 1, 1)),
                    )
                ),
                employee_record_exists=Exists(
                    EmployeeRecord.objects.filter(
                        job_application__to_siae=OuterRef("to_siae"), approval_number=OuterRef("approval__number")
                    )
                ),
            )
            .filter(
                # Must be linked to an approval with a Suspension or a Prolongation
                Q(has_recent_suspension=True) | Q(has_recent_prolongation=True),
                # Only for that SIAE
                to_siae=siae,
                # Hiring structure must be one of those kinds
                # FIXME(rsebille): should probably not be handled as SQL because we already have `siae`
                to_siae__kind__in=Siae.ASP_EMPLOYEE_RECORD_KINDS,
                # Admin control: can prevent creation of employee record
                create_employee_record=True,
                # There must be **NO** employee record linked in this part
                employee_record__isnull=True,
                # Exclude the job application if an employee record with the same SIAE and approval already exists.
                employee_record_exists=False,
            )
        )

    def eligible_as_employee_record(self, siae):
        """
        Get a list of job applications potentially "updatable" as an employee record.
        For display concerns (list of employee records for a given SIAE).

        Rules of eligibility for a job application:
            - be in 'ACCEPTED' state (valid hiring)
            - to be linked to an approval
            - hiring SIAE must be one of : AI, EI, ACI, ETTI. EITI will be added as of september 2022
            - the hiring date must be greater than 2021.09.27 (feature production date)
            - employee record is not blocked via admin (`create_employee_record` field)

        Enabling / disabling an employee record has no impact on job application eligibility concerns.

        Getting a correct list of eligible job applications for employee records:
            - is not achievable in one single request (opposite conditions)
            - is consuming a lot of resources (200-800ms per round)
        Splitting in multiple queries, reunited by a UNION:
            - lowers SQL query time under 30ms
            - adds correctness to result
        Each query is commented according to the newest Whimsical schemas.
        """
        eligible_job_applications = JobApplicationQuerySet.union(
            self._eligible_job_applications_with_employee_record(siae),
            self._eligible_job_applications_without_employee_record(siae),
            self._eligible_job_applications_with_a_suspended_or_extended_approval(siae),
        )

        # TIP: you can't filter on a UNION of querysets,
        # but you can convert it as a subquery and then order and filter it
        return (
            self.filter(pk__in=eligible_job_applications.values("id"))
            .select_related("to_siae", "to_siae__convention", "approval", "job_seeker")
            .prefetch_related("employee_record", "approval__suspension_set", "approval__prolongation_set")
            .order_by("-hiring_start_at")
        )


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    A job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    # Copy those values here, as they are used in templates ( `if self.kind == self.SENDER_KIND_XXX` )
    # It's either this, or:
    # - we create special properties such as `is_job_seeker()`, but this is ugly and tedious.
    # - we inject the SenderKind constants through the context, but it needs to be passed down to includes
    #   which makes them extra complex (template arguments) for no good reason.
    # - we create a global context that includes those constants but it's hiding the logic somewhere and
    #   thus creating "magic" templates.
    # - we split the views for every kind, but it's not trivial since we would have to refactor the included
    #   templates logic for every view.
    # This is not very DRY, but clearly is the clearest solution. Disclaimer: I tried the others.
    SENDER_KIND_JOB_SEEKER = SenderKind.JOB_SEEKER
    SENDER_KIND_PRESCRIBER = SenderKind.PRESCRIBER
    SENDER_KIND_SIAE_STAFF = SenderKind.SIAE_STAFF

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
        choices=SenderKind.choices,
        default=SenderKind.PRESCRIBER,
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
        verbose_name="Motifs de refus", max_length=30, choices=RefusalReason.choices, blank=True
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

    transferred_at = models.DateTimeField(verbose_name="Date de transfert", null=True, blank=True)
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Transferée par", null=True, blank=True, on_delete=models.SET_NULL
    )
    transferred_from = models.ForeignKey(
        "siaes.Siae",
        verbose_name="SIAE d'origine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_application_transferred",
    )

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
            self.sender_kind == SenderKind.PRESCRIBER
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
    def can_display_approval(self):
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
            and self.refusal_reason == RefusalReason.DEACTIVATION.value
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

    def get_sender_kind_display(self):
        # Override default getter since we want to separate Orienteur and Prescripteur
        if self.sender_kind == SenderKind.PRESCRIBER and (
            not self.sender_prescriber_organization or not self.sender_prescriber_organization.is_authorized
        ):
            return "Orienteur"
        else:
            return SenderKind(self.sender_kind).label

    @property
    def candidate_has_employee_record(self):

        if not self.approval:
            return False

        if self.employee_record.exists():
            return True

        # check if employee_record for the same approval in the same siae exists
        return self.approval.jobapplication_set.filter(
            employee_record__asp_id=self.to_siae.convention.asp_id,
            employee_record__approval_number=self.approval.number,
        ).exists()

    @property
    def is_waiting_for_employee_record_creation(self):
        """
        Check if EmployeeRecord does not exist and can be created for this JobApplication.
        """
        is_application_valid = (
            self.hiring_start_at is not None
            and self.hiring_start_at >= EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date()
            and not self.hiring_without_approval
            and self.state == JobApplicationWorkflow.STATE_ACCEPTED
            and self.approval.is_valid()
        )

        return is_application_valid and not self.candidate_has_employee_record and self.to_siae.can_use_employee_record

    @property
    def is_in_transferable_state(self):
        return self.state not in [JobApplicationWorkflow.STATE_ACCEPTED, JobApplicationWorkflow.STATE_NEW]

    def can_be_transferred(self, user, target_siae):
        # User must be member of both origin and target SIAE to make a transfer
        if not (self.to_siae.has_member(user) and target_siae.has_member(user)):
            return False
        # Can't transfer to same structure
        if target_siae == self.to_siae:
            return False
        # User must be SIAE user / employee
        if not user.is_siae_staff:
            return False
        return self.is_in_transferable_state

    def transfer_to(self, transferred_by, target_siae):
        if not (self.is_in_transferable_state and self.can_be_transferred(transferred_by, target_siae)):
            raise ValidationError(
                f"Cette candidature n'est pas transferable ({transferred_by=}, {target_siae=}, {self.to_siae=})"
            )

        self.transferred_from = self.to_siae
        self.transferred_by = transferred_by
        self.transferred_at = timezone.now()
        self.to_siae = target_siae
        self.state = JobApplicationWorkflow.STATE_NEW
        # Consider job application as new : don't keep answers
        self.answer = self.answer_to_prescriber = ""

        # Delete eligibility diagnosis if not provided by an authorized prescriber
        eligibility_diagnosis = self.eligibility_diagnosis
        is_eligibility_diagnosis_made_by_siae = (
            eligibility_diagnosis and eligibility_diagnosis.author_kind == EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF
        )
        if is_eligibility_diagnosis_made_by_siae:
            self.eligibility_diagnosis = None

        self.save(
            update_fields=[
                "eligibility_diagnosis",
                "to_siae",
                "state",
                "transferred_at",
                "transferred_by",
                "transferred_from",
                "answer",
                "answer_to_prescriber",
            ]
        )

        # As 1:N or 1:1 objects must have a pk before being saved,
        # eligibility diagnosis must be deleted after saving current object.
        if is_eligibility_diagnosis_made_by_siae:
            eligibility_diagnosis.delete()

        # Always send an email to job seeker and origin SIAE
        emails = [
            self.get_email_transfer_origin_siae(transferred_by, self.transferred_from, target_siae),
            self.get_email_transfer_job_seeker(transferred_by, self.transferred_from, target_siae),
        ]

        # Send email to prescriber or orienter if any
        if self.sender_kind == self.SENDER_KIND_PRESCRIBER:
            emails.append(self.get_email_transfer_prescriber(transferred_by, self.transferred_from, target_siae))

        send_email_messages(emails)

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

            if self.job_seeker.has_common_approval_in_waiting_period:
                if self.job_seeker.approval_can_be_renewed_by(
                    siae=self.to_siae, sender_prescriber_organization=self.sender_prescriber_organization
                ):
                    # Security check: it's supposed to be blocked upstream.
                    raise xwf_models.AbortTransition("Job seeker has an approval in waiting period.")

            if self.job_seeker.has_valid_common_approval:
                # Automatically reuse an existing valid Itou or PE approval.
                self.approval = self.job_seeker.get_or_create_approval()
                if self.approval.start_at > self.hiring_start_at:
                    # As a job seeker can have multiple contracts at the same time,
                    # the approval should start at the same time as most recent contract.
                    self.approval.update_start_date(new_start_date=self.hiring_start_at)
                emails.append(self.email_deliver_approval(accepted_by))
            elif (
                self.job_seeker.has_no_common_approval and (self.job_seeker.nir or self.job_seeker.pole_emploi_id)
            ) or (
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
            elif not self.job_seeker.nir or (
                not self.job_seeker.pole_emploi_id
                and self.job_seeker.lack_of_pole_emploi_id_reason == self.job_seeker.REASON_FORGOTTEN
            ):
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
        send_email_messages(emails)

        if self.approval:
            self.approval_number_sent_by_email = True
            self.approval_number_sent_at = timezone.now()
            self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_AUTOMATIC
            self.approval.unsuspend(self.hiring_start_at)
            # FIXME(vperron): This is an unelegant method to avoid using huey
            # in local development, thus needing Redis. Maybe some development
            # settings involving a local, in-memory huey in immediate mode would
            # be better, but this is a fast fix.
            if settings.API_ESD["BASE_URL"]:
                huey_notify_pole_emploi(self)

    @xwf_models.transition()
    def refuse(self, *args, **kwargs):
        # Send notification.
        emails = [self.email_refuse_for_job_seeker]
        if self.is_sent_by_proxy:
            emails.append(self.email_refuse_for_proxy)
        send_email_messages(emails)

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
        send_email_messages([self.email_cancel(cancelled_by=user)])

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

    def email_new_for_job_seeker(self):
        to = [self.job_seeker.email]
        context = {"job_application": self, "base_url": get_absolute_url().rstrip("/")}
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

    def _get_transfer_email(self, to, subject, body, transferred_by, origin_siae, target_siae):
        context = {
            "job_application": self,
            "transferred_by": transferred_by,
            "origin_siae": origin_siae,
            "target_siae": target_siae,
        }
        return get_email_message(to, context, subject, body)

    def get_email_transfer_origin_siae(self, transferred_by, origin_siae, target_siae):
        # Send email to every active member of the origin SIAE
        to = list(origin_siae.active_members.values_list("email", flat=True))
        subject = "apply/email/transfer_origin_siae_subject.txt"
        body = "apply/email/transfer_origin_siae_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_siae, target_siae)

    def get_email_transfer_job_seeker(self, transferred_by, origin_siae, target_siae):
        to = [self.job_seeker.email]
        subject = "apply/email/transfer_job_seeker_subject.txt"
        body = "apply/email/transfer_job_seeker_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_siae, target_siae)

    def get_email_transfer_prescriber(self, transferred_by, origin_siae, target_siae):
        to = [self.sender.email]
        subject = "apply/email/transfer_prescriber_subject.txt"
        body = "apply/email/transfer_prescriber_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_siae, target_siae)

    def manually_deliver_approval(self, delivered_by):
        self.approval_number_sent_by_email = True
        self.approval_number_sent_at = timezone.now()
        self.approval_manually_delivered_by = delivered_by
        self.save()
        # Send email at the end because we can't rollback this operation
        email = self.email_deliver_approval(self.accepted_by)
        email.send()

    def manually_refuse_approval(self, refused_by):
        self.approval_manually_refused_by = refused_by
        self.approval_manually_refused_at = timezone.now()
        self.save()
        # Send email at the end because we can't rollback this operation
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
        verbose_name = "Log des transitions de la candidature"
        verbose_name_plural = "Log des transitions des candidatures"
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.id)

    @property
    def pretty_to_state(self):
        choices = dict(JobApplicationWorkflow.STATE_CHOICES)
        return choices[self.to_state]
