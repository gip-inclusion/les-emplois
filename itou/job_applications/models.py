import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, Count, Exists, F, Func, Max, OuterRef, Prefetch, Q, Subquery, When
from django.db.models.functions import Coalesce, Greatest, TruncMonth
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models
from xworkflows import before_transition

from itou.approvals.models import Approval, Suspension
from itou.approvals.notifications import PassAcceptedEmployerNotification
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models import EligibilityDiagnosis, SelectedAdministrativeCriteria
from itou.employee_record.models import EmployeeRecord
from itou.files.models import File
from itou.gps.models import FollowUpGroup
from itou.job_applications import notifications as job_application_notifications
from itou.job_applications.enums import (
    ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL,
    AUTO_REJECT_JOB_APPLICATION_DELAY,
    AUTO_REJECT_JOB_APPLICATION_STATES,
    GEIQ_MAX_HOURS_PER_WEEK,
    GEIQ_MIN_HOURS_PER_WEEK,
    JobApplicationState,
    Origin,
    Prequalification,
    ProfessionalSituationExperience,
    QualificationLevel,
    QualificationType,
    RefusalReason,
    SenderKind,
)
from itou.rdv_insertion.models import Participation
from itou.users.enums import LackOfPoleEmploiId, UserKind
from itou.utils.emails import get_email_message
from itou.utils.models import InclusiveDateRangeField
from itou.utils.urls import get_absolute_url


class JobApplicationWorkflow(xwf_models.Workflow):
    """
    The JobApplication workflow.
    https://django-xworkflows.readthedocs.io/
    """

    states = JobApplicationState.choices

    TRANSITION_PROCESS = "process"
    TRANSITION_POSTPONE = "postpone"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_MOVE_TO_PRIOR_TO_HIRE = "move_to_prior_to_hire"
    TRANSITION_CANCEL_PRIOR_TO_HIRE = "cancel_prior_to_hire"
    TRANSITION_REFUSE = "refuse"
    TRANSITION_CANCEL = "cancel"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"
    TRANSITION_TRANSFER = "transfer"
    TRANSITION_EXTERNAL_TRANSFER = "external_transfer"
    TRANSITION_RESET = "reset"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, "Étudier la candidature"),
        (TRANSITION_POSTPONE, "Reporter la candidature"),
        (TRANSITION_ACCEPT, "Accepter la candidature"),
        (TRANSITION_MOVE_TO_PRIOR_TO_HIRE, "Passer en pré-embauche"),
        (TRANSITION_CANCEL_PRIOR_TO_HIRE, "Annuler la pré-embauche"),
        (TRANSITION_REFUSE, "Décliner la candidature"),
        (TRANSITION_CANCEL, "Annuler la candidature"),
        (TRANSITION_RENDER_OBSOLETE, "Rendre obsolete la candidature"),
        (TRANSITION_TRANSFER, "Transfert de la candidature vers une autre entreprise de l'utilisateur"),
        (TRANSITION_RESET, "Réinitialiser la candidature"),
        (TRANSITION_EXTERNAL_TRANSFER, "Transfert de la candidature vers une entreprise externe"),
    )

    CAN_BE_ACCEPTED_STATES = [
        JobApplicationState.NEW,
        JobApplicationState.PROCESSING,
        JobApplicationState.POSTPONED,
        JobApplicationState.PRIOR_TO_HIRE,
        JobApplicationState.OBSOLETE,
        JobApplicationState.REFUSED,
        JobApplicationState.CANCELLED,
    ]
    CAN_BE_TRANSFERRED_STATES = CAN_BE_ACCEPTED_STATES
    CAN_BE_REFUSED_STATES = [
        JobApplicationState.NEW,
        JobApplicationState.PROCESSING,
        JobApplicationState.PRIOR_TO_HIRE,
        JobApplicationState.POSTPONED,
    ]
    CAN_ADD_PRIOR_ACTION_STATES = [
        JobApplicationState.NEW,
        JobApplicationState.PROCESSING,
        JobApplicationState.POSTPONED,
        JobApplicationState.OBSOLETE,
        JobApplicationState.REFUSED,
        JobApplicationState.CANCELLED,
    ]
    JOB_APPLICATION_PROCESSED_STATES = [
        JobApplicationState.ACCEPTED,
        JobApplicationState.REFUSED,
        JobApplicationState.CANCELLED,
        JobApplicationState.OBSOLETE,
    ]
    CAN_BE_POSTPONED_STATES = [
        JobApplicationState.NEW,
        JobApplicationState.PROCESSING,
        JobApplicationState.PRIOR_TO_HIRE,
    ]

    transitions = (
        (TRANSITION_PROCESS, JobApplicationState.NEW, JobApplicationState.PROCESSING),
        (TRANSITION_POSTPONE, CAN_BE_POSTPONED_STATES, JobApplicationState.POSTPONED),
        (TRANSITION_ACCEPT, CAN_BE_ACCEPTED_STATES, JobApplicationState.ACCEPTED),
        (TRANSITION_MOVE_TO_PRIOR_TO_HIRE, CAN_ADD_PRIOR_ACTION_STATES, JobApplicationState.PRIOR_TO_HIRE),
        (TRANSITION_CANCEL_PRIOR_TO_HIRE, [JobApplicationState.PRIOR_TO_HIRE], JobApplicationState.PROCESSING),
        (TRANSITION_REFUSE, CAN_BE_REFUSED_STATES, JobApplicationState.REFUSED),
        (TRANSITION_CANCEL, JobApplicationState.ACCEPTED, JobApplicationState.CANCELLED),
        (
            TRANSITION_RENDER_OBSOLETE,
            [JobApplicationState.NEW, JobApplicationState.PROCESSING, JobApplicationState.POSTPONED],
            JobApplicationState.OBSOLETE,
        ),
        (TRANSITION_TRANSFER, CAN_BE_TRANSFERRED_STATES, JobApplicationState.NEW),
        (TRANSITION_RESET, JobApplicationState.OBSOLETE, JobApplicationState.NEW),
        (TRANSITION_EXTERNAL_TRANSFER, JobApplicationState.REFUSED, JobApplicationState.REFUSED),
    )

    PENDING_STATES = [JobApplicationState.NEW, JobApplicationState.PROCESSING, JobApplicationState.POSTPONED]
    initial_state = JobApplicationState.NEW

    log_model = "job_applications.JobApplicationTransitionLog"

    error_missing_hiring_start_at = "Cannot accept a job application with no hiring start date."
    error_hires_after_pass_invalid = "Cannot use an approval which ends before the hiring start date."
    error_wrong_eligibility_diagnosis = "Cannot use the eligibility diagnosis"
    error_missing_eligibility_diagnostic = "Cannot create an approval without eligibility diagnosis here."


class JobApplicationQuerySet(models.QuerySet):
    def is_active_company_member(self, user):
        return self.filter(
            Exists(CompanyMembership.objects.active().filter(user=user, company=OuterRef("to_company")))
        )

    def pending(self):
        return self.filter(state__in=JobApplicationWorkflow.PENDING_STATES)

    def accepted(self):
        return self.filter(state=JobApplicationState.ACCEPTED)

    def created_on_given_year_and_month(self, year, month):
        return self.filter(created_at__year=year, created_at__month=month)

    def get_unique_fk_objects(self, fk_field):
        """
        Get unique foreign key objects in a single query.
        TODO: move this method in a custom manager since it's not chainable.
        """
        # FIXME: Replace that static list by a dynamic one
        if fk_field not in [
            "approval",
            "job_seeker",
            "sender",
            "sender_company",
            "sender_prescriber_organization",
            "to_company",
        ]:
            raise RuntimeError("Unauthorized fk_field")

        # Use the `_id` field because ordering by a ForeignKey will follow the Meta.ordering but the distinct will not.
        job_applications = self.order_by(f"{fk_field}_id").distinct(f"{fk_field}_id").select_related(fk_field)
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
        Returns objects that require a manual PASS IAE delivery.
        """
        return self.filter(
            state=JobApplicationState.ACCEPTED,
            approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL,
            approval_number_sent_by_email=False,
            approval_manually_refused_at=None,
        )

    def with_has_suspended_approval(self):
        has_suspended_approval = Suspension.objects.filter(approval=OuterRef("approval")).in_progress()
        return self.annotate(has_suspended_approval=Exists(has_suspended_approval))

    # We should store this in dedicated field and update it at each model.save()
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
                # Mega Super duper special case to handle job applications created to generate AI's PASS IAE
                When(
                    origin=Origin.AI_STOCK,
                    then=F("hiring_start_at"),
                ),
                When(origin=Origin.PE_APPROVAL, then=F("created_at")),
                When(
                    state=JobApplicationState.ACCEPTED,
                    # A job_application created at the accepted status will
                    # not have transitions logs, fallback on created_at
                    then=Coalesce(created_at_from_transition, F("created_at")),
                ),
                default=created_at_from_transition,
                output_field=models.DateTimeField(),
            )
        )

    def with_jobseeker_valid_eligibility_diagnosis(self):
        """
        Gives the last valid eligibility diagnosis for this job seeker and this SIAE
        """
        sub_query = Subquery(
            (
                EligibilityDiagnosis.objects.valid()
                .for_job_seeker_and_siae(job_seeker=OuterRef("job_seeker"), siae=OuterRef("to_company"))
                .values("id")[:1]
            ),
            output_field=models.IntegerField(),
        )
        return self.annotate(jobseeker_valid_eligibility_diagnosis=sub_query)

    def with_jobseeker_eligibility_diagnosis(self):
        """
        Gives the "eligibility_diagnosis" linked to the job application or if none is found
        the last valid eligibility diagnosis for this job seeker and this SIAE
        """
        return self.with_jobseeker_valid_eligibility_diagnosis().annotate(
            jobseeker_eligibility_diagnosis=Coalesce(
                F("eligibility_diagnosis"), F("jobseeker_valid_eligibility_diagnosis")
            )
        )

    def with_eligibility_diagnosis_criterion(self, criterion):
        """
        Create an annotation by criterion given (used in the filters form).
        The criterion parameter must be the primary key of an AdministrativeCriteria.
        """
        subquery = SelectedAdministrativeCriteria.objects.filter(
            eligibility_diagnosis=OuterRef("jobseeker_eligibility_diagnosis"), administrative_criteria=criterion
        )
        return self.annotate(**{f"eligibility_diagnosis_criterion_{criterion}": Exists(subquery)})

    def with_list_related_data(self, criteria=None):
        """
        Stop the deluge of database queries that is caused by accessing related
        objects in job applications's lists.
        """
        if criteria is None:
            criteria = []

        qs = self.select_related(
            "approval",
            "job_seeker__jobseeker_profile",
            "sender",
            "sender_company",
            "sender_prescriber_organization",
            "to_company__convention",
        ).prefetch_related(
            "selected_jobs__appellation",
            "selected_jobs__location",
            "selected_jobs__company",
            Prefetch("job_seeker__approvals", queryset=Approval.objects.order_by("-start_at")),
        )

        qs = qs.with_last_change().with_jobseeker_eligibility_diagnosis()

        # Adding an annotation by selected criterion
        for criterion in criteria:
            # The criterion given to this method is a primary key of an AdministrativeCriteria
            qs = qs.with_eligibility_diagnosis_criterion(int(criterion))

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

    def _get_participations_subquery(self):
        """
        Returns a RDVI participations subquery related to outer job applications
        """
        return Participation.objects.filter(
            appointment__company=OuterRef("to_company"),
            job_seeker=OuterRef("job_seeker"),
            status=Participation.Status.UNKNOWN,
            appointment__start_at__gt=timezone.now(),
        )

    def with_next_appointment_start_at(self):
        """
        Gives the next pending RDVI appointment datetime for this job seeker and this SIAE
        """
        return self.annotate(
            next_appointment_start_at=Subquery(
                self._get_participations_subquery()
                .order_by("appointment__start_at")
                .values("appointment__start_at")[:1],
                output_field=models.DateTimeField(),
            )
        )

    def with_upcoming_participations_count(self):
        """
        Gives the total count of pending RDVI appointments for this job seeker and this SIAE
        """
        return self.annotate(
            upcoming_participations_count=Subquery(
                self._get_participations_subquery()
                .annotate(count=Func(F("pk"), function="COUNT"))  # Count() adds an undesired GROUP BY
                .values("count"),
                output_field=models.IntegerField(),
            )
        )

    # Employee record querysets
    def eligible_as_employee_record(self, siae):
        """
        Get a list of job applications potentially "updatable" as an employee record.
        For display concerns (list of employees for a given SIAE).
        """
        if not siae.can_use_employee_record:
            return self.none()

        # Return the approvals already used by any SIAE of the convention
        approvals_to_exclude = EmployeeRecord.objects.for_asp_company(siae).values("approval_number")

        return (
            self.accepted()  # Must be accepted
            .filter(
                # Must be linked to an approval
                approval__isnull=False,
                # Only for that SIAE
                to_company=siae,
                # Admin control: can prevent creation of employee record
                create_employee_record=True,
                # There must be **NO** employee record linked in this part
                employee_record__isnull=True,
            )
            .exclude(approval__number__in=approvals_to_exclude)
            # show the most recent hiring first (and the one with null at the end)
            .order_by(F("hiring_start_at").desc(nulls_last=True))
        )

    def inconsistent_approval_user(self):
        return self.filter(approval__isnull=False).exclude(approval__user=F("job_seeker"))

    def inconsistent_eligibility_diagnosis_job_seeker(self):
        return self.filter(eligibility_diagnosis__isnull=False).exclude(
            eligibility_diagnosis__job_seeker=F("job_seeker")
        )

    def inconsistent_geiq_eligibility_diagnosis_job_seeker(self):
        return self.filter(geiq_eligibility_diagnosis__isnull=False).exclude(
            geiq_eligibility_diagnosis__job_seeker=F("job_seeker")
        )

    def prescriptions_of(self, user, organization=None):
        if user.is_prescriber:
            if organization:
                return self.filter(
                    (Q(sender=user) & Q(sender_prescriber_organization__isnull=True))
                    | Q(sender_prescriber_organization=organization)
                )
            else:
                return self.filter(sender=user)
        elif user.is_employer and organization:
            return self.filter(sender_company=organization).exclude(to_company=organization)
        return self.none()

    def automatically_rejectable_applications(self):
        return self.filter(
            state__in=AUTO_REJECT_JOB_APPLICATION_STATES,
            archived_at__isnull=True,
            updated_at__lte=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY,
        )


class JobApplication(xwf_models.WorkflowEnabled, models.Model):
    """
    A job application.

    It inherits from `xwf_models.WorkflowEnabled` to add a workflow to its `state` field:
        - https://github.com/rbarrois/django_xworkflows
        - https://github.com/rbarrois/xworkflows
    """

    # SIAE have the possibility to update the hiring date if:
    # - it is before the end date of an approval created for this job application
    # - it is in the future, max. MAX_CONTRACT_POSTPONE_IN_DAYS days from today.
    MAX_CONTRACT_POSTPONE_IN_DAYS = 30

    ERROR_START_IN_PAST = "Il n'est pas possible d'antidater un contrat. Indiquez une date dans le futur."
    ERROR_START_IN_FAR_FUTURE = (
        "Il n'est pas possible de faire commencer un contrat aussi loin dans le futur. Indiquez une date plus proche."
    )
    ERROR_END_IS_BEFORE_START = "La date de fin du contrat doit être postérieure à la date de début."
    ERROR_START_AFTER_APPROVAL_END = (
        "Attention, le PASS IAE sera expiré lors du début du contrat. Veuillez modifier la date de début."
    )
    ERROR_HIRES_AFTER_APPROVAL_EXPIRES = "Le contrat doit débuter sur la période couverte par le PASS IAE."
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
        verbose_name="demandeur d'emploi",
        on_delete=models.RESTRICT,  # This object is central to us and the SIAE
        related_name="job_applications",
    )

    # The job seeker's eligibility diagnosis used for this job application
    # (required for SIAEs subject to eligibility rules).
    # It is already linked to the job seeker but this double link is added
    # to easily find out which one was used for a given job application.
    # Use `self.get_eligibility_diagnosis()` to handle business rules.
    eligibility_diagnosis = models.ForeignKey(
        "eligibility.EligibilityDiagnosis",
        verbose_name="diagnostic d'éligibilité",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
    )

    geiq_eligibility_diagnosis = models.ForeignKey(
        "eligibility.GEIQEligibilityDiagnosis",
        verbose_name="diagnostic d'éligibilité GEIQ",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="job_applications",
    )

    # Exclude flagged approvals (batch creation or import of approvals).
    # See itou.users.management.commands.import_ai_employees.
    create_employee_record = models.BooleanField(default=True, verbose_name="création d'une fiche salarié")

    # The job seeker's resume used for this job application.
    resume = models.OneToOneField(File, null=True, blank=True, verbose_name="CV", on_delete=models.PROTECT)

    # Who send the job application. It can be the same user as `job_seeker`
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur émetteur",
        on_delete=models.RESTRICT,  # For traceability and accountability
        null=True,
        blank=True,
        related_name="job_applications_sent",
    )

    sender_kind = models.CharField(
        verbose_name="type de l'émetteur",
        choices=SenderKind.choices,
    )

    # When the sender is an employer, keep a track of his current company.
    sender_company = models.ForeignKey(
        "companies.Company", verbose_name="entreprise émettrice", null=True, blank=True, on_delete=models.RESTRICT
    )

    # When the sender is a prescriber, keep a track of his current organization (if any).
    sender_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation du prescripteur émettrice",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )

    to_company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise destinataire",
        on_delete=models.RESTRICT,
        related_name="job_applications_received",
    )

    state = xwf_models.StateField(JobApplicationWorkflow, verbose_name="état", db_index=True)
    archived_at = models.DateTimeField(blank=True, null=True, verbose_name="archivée le", db_index=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability.
        verbose_name="archivée par",
        related_name="+",
    )

    # Jobs in which the job seeker is interested (optional).
    selected_jobs = models.ManyToManyField("companies.JobDescription", verbose_name="métiers recherchés", blank=True)
    # Job for which the job seeker was hired (may not be among selected_jobs)
    hired_job = models.ForeignKey(
        "companies.JobDescription",
        verbose_name="poste retenu",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,  # SET_NULL so employers can delete job descriptions in their dashboards
        related_name="hired_job_applications",
    )

    message = models.TextField(verbose_name="message de candidature", blank=True)
    answer = models.TextField(verbose_name="message de réponse", blank=True)
    answer_to_prescriber = models.TextField(verbose_name="message de réponse au prescripteur", blank=True)
    refusal_reason = models.CharField(
        verbose_name="motifs de refus", max_length=30, choices=RefusalReason.choices, blank=True
    )
    refusal_reason_shared_with_job_seeker = models.BooleanField(
        verbose_name="partage du motif de refus avec le candidat", default=False
    )

    hiring_start_at = models.DateField(verbose_name="date de début du contrat", blank=True, null=True, db_index=True)
    hiring_end_at = models.DateField(verbose_name="date prévisionnelle de fin du contrat", blank=True, null=True)

    origin = models.CharField(
        verbose_name="origine de la candidature", max_length=30, choices=Origin.choices, default=Origin.DEFAULT
    )

    # Job applications sent to SIAEs subject to eligibility rules can obtain an
    # Approval after being accepted.
    approval = models.ForeignKey(
        "approvals.Approval", verbose_name="PASS IAE", null=True, blank=True, on_delete=models.RESTRICT
    )
    approval_delivery_mode = models.CharField(
        verbose_name="mode d'attribution du PASS IAE",
        max_length=30,
        choices=APPROVAL_DELIVERY_MODE_CHOICES,
        blank=True,
    )
    # Fields used for approvals processed both manually or automatically.
    approval_number_sent_by_email = models.BooleanField(verbose_name="PASS IAE envoyé par email", default=False)
    approval_number_sent_at = models.DateTimeField(
        verbose_name="date d'envoi du PASS IAE", blank=True, null=True, db_index=True
    )
    # Fields used only for manual processing.
    approval_manually_delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="PASS IAE délivré manuellement par",
        on_delete=models.RESTRICT,  # For traceability and accountability
        null=True,
        blank=True,
        related_name="approval_manually_delivered",
    )
    approval_manually_refused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="PASS IAE refusé manuellement par",
        on_delete=models.RESTRICT,  # For traceability and accountability
        null=True,
        blank=True,
        related_name="approval_manually_refused",
    )
    approval_manually_refused_at = models.DateTimeField(
        verbose_name="date de refus manuel du PASS IAE", blank=True, null=True
    )

    transferred_at = models.DateTimeField(verbose_name="date de transfert", null=True, blank=True)
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="transférée par",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    transferred_from = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise d'origine",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="job_application_transferred",
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)
    # Whenever a job application enters a "processed" state (see JOB_APPLICATION_PROCESSED_STATES)
    # we store the timestamp here.
    processed_at = models.DateTimeField(verbose_name="date de traitement", null=True, blank=True)

    # GEIQ only
    prehiring_guidance_days = models.PositiveSmallIntegerField(
        verbose_name="nombre de jours d’accompagnement avant contrat",
        blank=True,
        null=True,
    )
    contract_type = models.CharField(
        verbose_name="type de contrat",
        max_length=30,
        choices=ContractType.choices_for_company_kind(CompanyKind.GEIQ),
        blank=True,
    )
    nb_hours_per_week = models.PositiveSmallIntegerField(
        verbose_name="nombre d'heures par semaine",
        blank=True,
        null=True,
        validators=[
            MinValueValidator(GEIQ_MIN_HOURS_PER_WEEK),
            MaxValueValidator(GEIQ_MAX_HOURS_PER_WEEK),
        ],
    )
    contract_type_details = models.TextField(verbose_name="précisions sur le type de contrat", blank=True)

    qualification_type = models.CharField(
        verbose_name="type de qualification visé",
        max_length=20,
        choices=QualificationType.choices,
        blank=True,
    )
    qualification_level = models.CharField(
        verbose_name="niveau de qualification visé",
        max_length=40,
        choices=QualificationLevel.choices,
        blank=True,
    )

    planned_training_hours = models.PositiveSmallIntegerField(
        verbose_name="nombre d'heures de formation prévues",
        blank=True,
        null=True,
    )

    inverted_vae_contract = models.BooleanField(
        verbose_name="contrat associé à une VAE inversée",
        blank=True,
        null=True,
    )

    # Diagoriente
    diagoriente_invite_sent_at = models.DateTimeField(
        verbose_name="date d'envoi de l'invitation à utiliser Diagoriente",
        null=True,
        editable=False,
    )

    objects = JobApplicationQuerySet.as_manager()

    class Meta:
        verbose_name = "candidature"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                name="geiq_fields_coherence",
                violation_error_message="Incohérence dans les champs concernant le contrat GEIQ",
                condition=models.Q(
                    contract_type__in=[ContractType.PROFESSIONAL_TRAINING, ContractType.APPRENTICESHIP],
                    contract_type_details="",
                    nb_hours_per_week__gt=0,
                )
                | (
                    models.Q(contract_type=ContractType.OTHER, nb_hours_per_week__gt=0)
                    & ~models.Q(contract_type_details="")
                )
                | models.Q(
                    contract_type="",
                    contract_type_details="",
                    nb_hours_per_week=None,
                ),
            ),
            models.CheckConstraint(
                name="diagnoses_coherence",
                violation_error_message="Une candidature ne peut avoir les deux types de diagnostics (IAE et GEIQ)",
                condition=~models.Q(eligibility_diagnosis__isnull=False, geiq_eligibility_diagnosis__isnull=False),
            ),
            models.CheckConstraint(
                name="qualification_coherence",
                violation_error_message="Incohérence dans les champs concernant la qualification pour le contrat GEIQ",
                condition=~models.Q(
                    qualification_level=QualificationLevel.NOT_RELEVANT,
                    qualification_type=QualificationType.STATE_DIPLOMA,
                ),
            ),
            models.CheckConstraint(
                name="processed_coherence",
                violation_error_message="Incohérence du champ date de traitement",
                condition=models.Q(
                    state__in=JobApplicationWorkflow.JOB_APPLICATION_PROCESSED_STATES, processed_at__isnull=False
                )
                | (
                    ~models.Q(state__in=JobApplicationWorkflow.JOB_APPLICATION_PROCESSED_STATES)
                    & models.Q(processed_at=None)
                ),
            ),
            models.CheckConstraint(
                name="archived_status",
                violation_error_message=(
                    "Impossible d’archiver une candidature acceptée ou en action préalable à l’embauche."
                ),
                condition=~models.Q(
                    state__in=[JobApplicationState.ACCEPTED, JobApplicationState.PRIOR_TO_HIRE],
                    archived_at__isnull=False,
                ),
            ),
            models.CheckConstraint(
                name="archived_by__no_archived_at",
                violation_error_message="Une candidature active ne peut pas avoir été archivée par un utilisateur.",
                condition=~models.Q(archived_at=None, archived_by__isnull=False),
            ),
            models.CheckConstraint(
                name="job_seeker_sender_coherence",
                violation_error_message="Le candidat doit être l'émetteur de la candidature",
                condition=(~models.Q(sender_kind="job_seeker") | models.Q(job_seeker=F("sender"))),
            ),
            models.CheckConstraint(
                name="employer_sender_coherence",
                violation_error_message="Données incohérentes pour une candidature employeur",
                condition=(
                    ~models.Q(sender_kind="employer")
                    | models.Q(
                        sender_kind="employer", sender_company__isnull=False, sender_prescriber_organization=None
                    )
                ),
            ),
            models.CheckConstraint(
                name="prescriber_sender_coherence",
                violation_error_message="Données incohérentes pour une candidature prescripteur",
                condition=(
                    ~models.Q(sender_kind="prescriber") | models.Q(sender_kind="prescriber", sender_company=None)
                ),
            ),
        ]
        permissions = [
            ("export_job_applications_unknown_to_ft", "Can export job applications of job seekers unknown to FT")
        ]

    def __str__(self):
        return str(self.id)

    def clean(self):
        super().clean()

        if self.job_seeker_id and self.job_seeker.kind != UserKind.JOB_SEEKER:
            raise ValidationError(
                "Impossible de candidater pour cet utilisateur, celui-ci n'est pas un compte candidat"
            )

        # `to_company` is not guaranteed to exist if a `full_clean` is performed in some occasions
        # (f.i. in an admin form) checking existence of `to_company_id` keeps us safe here
        if self.to_company_id and self.to_company.kind != CompanyKind.GEIQ:
            if self.contract_type:
                raise ValidationError("Le type de contrat ne peut être saisi que pour un GEIQ")
            if self.contract_type_details:
                raise ValidationError("Les précisions sur le type de contrat ne peuvent être saisies que pour un GEIQ")
            if self.nb_hours_per_week:
                raise ValidationError("Le nombre d'heures par semaine ne peut être saisi que pour un GEIQ")
            if self.inverted_vae_contract is not None:
                raise ValidationError("Un contrat associé à une VAE inversée n'est possible que pour les GEIQ")

        if self.sender and self.sender_kind != self.sender.kind:
            raise ValidationError(
                "Le type de l'émetteur de la candidature ne correspond pas au type de l'utilisateur émetteur"
            )

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

    def eligibility_diagnosis_by_siae_required(self):
        """
        Returns True if an eligibility diagnosis must be made by an SIAE
        when processing an application, False otherwise.
        """
        return self.to_company.is_subject_to_eligibility_rules and not self.job_seeker.has_valid_diagnosis(
            for_siae=self.to_company
        )

    @property
    def manual_approval_delivery_required(self):
        """
        Returns True if the current instance require a manual PASS IAE delivery, False otherwise.
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
        return self.logs.select_related("user").filter(to_state=JobApplicationState.ACCEPTED).last().user

    @property
    def refused_by(self):
        if self.state.is_refused and (
            last_log := self.logs.select_related("user").filter(to_state=JobApplicationState.REFUSED).last()
        ):
            return last_log.user

    @property
    def can_be_cancelled(self):
        if self.origin == Origin.AI_STOCK:
            return False

        # If a job application is linked to an employee record then it can only be cancelled if we didn't send any data
        if any(er.was_sent() for er in self.employee_record.all()):
            return False

        return True

    @property
    def can_be_archived(self):
        return not self.archived_at and self.state in ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL

    @property
    def can_have_prior_action(self):
        return self.to_company.can_have_prior_action

    @property
    def can_change_prior_actions(self):
        return self.can_have_prior_action and not self.state.is_accepted

    @property
    def is_refused_due_to_deactivation(self):
        return self.state == JobApplicationState.REFUSED and self.refusal_reason == RefusalReason.DEACTIVATION.value

    @property
    def is_refused_for_other_reason(self):
        return self.state.is_refused and self.refusal_reason == RefusalReason.OTHER

    @property
    def hiring_starts_in_future(self):
        if self.hiring_start_at:
            return timezone.localdate() < self.hiring_start_at
        return False

    @property
    def can_update_hiring_start(self):
        return self.hiring_starts_in_future and self.state in [
            JobApplicationState.ACCEPTED,
            JobApplicationState.POSTPONED,
        ]

    @property
    def resume_link(self):
        if self.resume_id:
            return self.resume.public_url()
        return ""

    def get_sender_kind_display(self):
        # Override default getter since we want to separate Orienteur and Prescripteur
        if self.sender_kind == SenderKind.PRESCRIBER and (
            not self.sender_prescriber_organization or not self.sender_prescriber_organization.is_authorized
        ):
            return "Orienteur"
        elif self.sender_kind == SenderKind.EMPLOYER and self.to_company.kind not in CompanyKind.siae_kinds():
            # Not an SIAE per se
            return "Employeur"
        else:
            return SenderKind(self.sender_kind).label

    def can_be_transferred(self, user, target_company):
        # User must be member of both origin and target companies to make a transfer
        if not (self.to_company.has_member(user) and target_company.has_member(user)):
            return False
        # Can't transfer to same structure
        if target_company == self.to_company:
            return False
        if not user.is_employer:
            return False
        return self.transfer.is_available()

    def get_eligibility_diagnosis(self):
        """
        Returns the eligibility diagnosis linked to this job application or None.
        """
        if not self.to_company.is_subject_to_eligibility_rules:
            return None
        if self.eligibility_diagnosis:
            return self.eligibility_diagnosis
        # As long as the job application has not been accepted, diagnosis-related
        # business rules may still prioritize one diagnosis over another.
        return EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, for_siae=self.to_company)

    # Workflow transitions.
    @before_transition(
        JobApplicationWorkflow.TRANSITION_ACCEPT,
        JobApplicationWorkflow.TRANSITION_REFUSE,
        JobApplicationWorkflow.TRANSITION_CANCEL,
        JobApplicationWorkflow.TRANSITION_RENDER_OBSOLETE,
    )
    def set_processed_at(self, *args, **kwargs):
        self.processed_at = timezone.now()

    @before_transition(
        JobApplicationWorkflow.TRANSITION_PROCESS,
        JobApplicationWorkflow.TRANSITION_POSTPONE,
        JobApplicationWorkflow.TRANSITION_MOVE_TO_PRIOR_TO_HIRE,
        JobApplicationWorkflow.TRANSITION_CANCEL_PRIOR_TO_HIRE,
        JobApplicationWorkflow.TRANSITION_TRANSFER,
        JobApplicationWorkflow.TRANSITION_RESET,
    )
    def unset_processed_at(self, *args, **kwargs):
        self.processed_at = None

    @before_transition(
        JobApplicationWorkflow.TRANSITION_PROCESS,
        JobApplicationWorkflow.TRANSITION_POSTPONE,
        JobApplicationWorkflow.TRANSITION_ACCEPT,
        JobApplicationWorkflow.TRANSITION_MOVE_TO_PRIOR_TO_HIRE,
        JobApplicationWorkflow.TRANSITION_CANCEL_PRIOR_TO_HIRE,
        JobApplicationWorkflow.TRANSITION_REFUSE,
        JobApplicationWorkflow.TRANSITION_CANCEL,
        JobApplicationWorkflow.TRANSITION_RENDER_OBSOLETE,
        JobApplicationWorkflow.TRANSITION_TRANSFER,
        JobApplicationWorkflow.TRANSITION_RESET,
    )
    def unarchive(self, *args, **kwargs):
        self.archived_at = None
        self.archived_by = None

    @xwf_models.transition()
    def transfer(self, *, user, target_company):
        if not self.can_be_transferred(user, target_company):
            raise ValidationError(
                f"Cette candidature n'est pas transférable ({user=}, {target_company=}, {self.to_company=})"
            )

        self.transferred_from = self.to_company
        self.transferred_by = user
        self.transferred_at = timezone.now()
        self.to_company = target_company
        self.state = JobApplicationState.NEW
        # Consider job application as new : don't keep answers
        self.answer = self.answer_to_prescriber = ""

        # Delete eligibility diagnosis if not provided by an authorized prescriber
        eligibility_diagnosis = self.eligibility_diagnosis
        is_eligibility_diagnosis_made_by_siae = (
            eligibility_diagnosis and eligibility_diagnosis.author_kind == AuthorKind.EMPLOYER
        )
        if is_eligibility_diagnosis_made_by_siae:
            self.eligibility_diagnosis = None
            self.save(update_fields={"eligibility_diagnosis", "updated_at"})
            eligibility_diagnosis.delete()

        notification_context = {
            "job_application": self,
            "transferred_by": user,
            "origin_company": self.transferred_from,
            "target_company": target_company,
        }

        # Always send notifications to original SIAE members
        for previous_employer in self.transferred_from.active_members.all():
            self.notifications_transfer_for_previous_employer(previous_employer, notification_context).send()

        # Always send notification to job seeker
        self.notifications_transfer_for_job_seeker(notification_context).send()

        # Send a notification to prescriber or orienter if any
        if self.sender_kind == SenderKind.PRESCRIBER and self.sender_id:  # Sender user may have been deleted.
            self.notifications_transfer_for_proxy(notification_context).send()

    @xwf_models.transition()
    def accept(self, *, user):
        if not self.hiring_start_at:
            raise xwf_models.AbortTransition(JobApplicationWorkflow.error_missing_hiring_start_at)

        # Link to the job seeker's eligibility diagnosis.
        if self.to_company.is_subject_to_eligibility_rules:
            # If request user is itou_staff keep the existing eligibility diagnosis
            if user.kind == UserKind.ITOU_STAFF and self.eligibility_diagnosis:
                if not (
                    EligibilityDiagnosis.objects.for_job_seeker_and_siae(self.job_seeker, siae=self.to_company)
                    .filter(pk=self.eligibility_diagnosis.pk)
                    .exists()
                ):
                    raise xwf_models.AbortTransition(JobApplicationWorkflow.error_wrong_eligibility_diagnosis)
            else:
                self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                    self.job_seeker, for_siae=self.to_company
                )

        # Approval issuance logic.
        if self.to_company.is_subject_to_eligibility_rules:
            if self.job_seeker.has_latest_common_approval_in_waiting_period:
                if self.job_seeker.new_approval_blocked_by_waiting_period(
                    siae=self.to_company, sender_prescriber_organization=self.sender_prescriber_organization
                ):
                    # Security check: it's supposed to be blocked upstream.
                    raise xwf_models.AbortTransition("Job seeker has an approval in waiting period.")

            if self.job_seeker.has_valid_approval:
                # Automatically reuse an existing valid approval.
                self.approval = self.job_seeker.latest_approval
                if self.hiring_start_at > self.approval.end_at:
                    raise xwf_models.AbortTransition(JobApplicationWorkflow.error_hires_after_pass_invalid)
                if self.approval.start_at > self.hiring_start_at:
                    # As a job seeker can have multiple contracts at the same time,
                    # the approval should start at the same time as most recent contract.
                    self.approval.update_start_date(new_start_date=self.hiring_start_at)
                self.notifications_deliver_approval(user).send()
            elif (
                self.job_seeker.has_no_common_approval
                and (self.job_seeker.jobseeker_profile.nir or self.job_seeker.jobseeker_profile.pole_emploi_id)
            ) or (
                self.job_seeker.jobseeker_profile.pole_emploi_id
                or self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
                == LackOfPoleEmploiId.REASON_NOT_REGISTERED
            ):
                # Security check: it's supposed to be blocked upstream.
                if self.eligibility_diagnosis is None:
                    raise xwf_models.AbortTransition(JobApplicationWorkflow.error_missing_eligibility_diagnostic)
                # Automatically create a new approval.
                new_approval = Approval(
                    start_at=self.hiring_start_at,
                    end_at=Approval.get_default_end_date(self.hiring_start_at),
                    user=self.job_seeker,
                    eligibility_diagnosis=self.eligibility_diagnosis,
                    **Approval.get_origin_kwargs(self),
                )
                new_approval.save()
                self.approval = new_approval
                self.notifications_deliver_approval(user).send()
            elif not self.job_seeker.jobseeker_profile.nir or (
                not self.job_seeker.jobseeker_profile.pole_emploi_id
                and self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
                == LackOfPoleEmploiId.REASON_FORGOTTEN
            ):
                # Trigger a manual approval creation.
                self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_MANUAL
                self.email_manual_approval_delivery_required_notification(user).send()
            else:
                raise xwf_models.AbortTransition("Job seeker has an invalid PE status, cannot issue approval.")

        # Mark other related job applications as obsolete.
        for job_application in self.job_seeker.job_applications.exclude(pk=self.pk).pending():
            job_application.render_obsolete(user=user)

        # Notifications & emails.
        self.notifications_accept_for_job_seeker.send()
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            self.notifications_accept_for_proxy.send()

        if self.approval:
            self.approval_number_sent_by_email = True
            self.approval_number_sent_at = timezone.now()
            self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_AUTOMATIC
            self.approval.unsuspend(self.hiring_start_at)

        # Sync GPS groups
        FollowUpGroup.objects.follow_beneficiary(self.job_seeker, user)

    @xwf_models.transition()
    def postpone(self, *, user):
        # Send notification.
        self.notifications_postpone_for_job_seeker.send()
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            self.notifications_postpone_for_proxy.send()

    @xwf_models.transition()
    def refuse(self, *, user):
        # Send notification.
        self.notifications_refuse_for_job_seeker.send()
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            self.notifications_refuse_for_proxy.send()

    @xwf_models.transition()
    def cancel(self, *, user):
        if not self.can_be_cancelled:
            raise xwf_models.AbortTransition("Cette candidature n'a pu être annulée.")

        if self.approval and self.approval.can_be_deleted():
            self.approval.delete()
            self.approval = None

            # Remove flags on the job application about approval
            self.approval_number_sent_by_email = False
            self.approval_number_sent_at = None
            self.approval_delivery_mode = ""
            self.approval_manually_delivered_by = None

        for employee_record in self.employee_record.all():
            if not employee_record.was_sent():
                employee_record.delete()

        # Send notification.
        self.notifications_cancel_for_employer(user).send()
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            self.notifications_cancel_for_proxy.send()

    def manually_deliver_approval(self, delivered_by):
        self.approval_number_sent_by_email = True
        self.approval_number_sent_at = timezone.now()
        self.approval_manually_delivered_by = delivered_by
        self.save()
        # Send notification at the end because we can't rollback this operation
        self.notifications_deliver_approval(self.accepted_by).send()

    def manually_refuse_approval(self, refused_by):
        self.approval_manually_refused_by = refused_by
        self.approval_manually_refused_at = timezone.now()
        self.save()
        # Send email at the end because we can't rollback this operation
        email = self.email_manually_refuse_approval
        email.send()

    # Notifications
    def notifications_new_for_employer(self, employer):
        return job_application_notifications.JobApplicationNewForEmployerNotification(
            employer,
            self.to_company,
            job_application=self,
        )

    @property
    def notifications_new_for_proxy(self):
        return job_application_notifications.JobApplicationNewForProxyNotification(
            self.sender,
            self.sender_prescriber_organization or self.sender_company,
            job_application=self,
        )

    @property
    def notifications_new_for_job_seeker(self):
        return job_application_notifications.JobApplicationNewForJobSeekerNotification(
            self.job_seeker,
            job_application=self,
            base_url=get_absolute_url().rstrip("/"),
        )

    @property
    def notifications_accept_for_job_seeker(self):
        return job_application_notifications.JobApplicationAcceptedForJobSeekerNotification(
            self.job_seeker,
            job_application=self,
        )

    @property
    def notifications_accept_for_proxy(self):
        return job_application_notifications.JobApplicationAcceptedForProxyNotification(
            self.sender,
            self.sender_prescriber_organization or self.sender_company,
            job_application=self,
        )

    @property
    def notifications_postpone_for_proxy(self):
        return job_application_notifications.JobApplicationPostponedForProxyNotification(
            self.sender,
            self.sender_prescriber_organization or self.sender_company,
            job_application=self,
        )

    @property
    def notifications_postpone_for_job_seeker(self):
        return job_application_notifications.JobApplicationPostponedForJobSeekerNotification(
            self.job_seeker,
            job_application=self,
        )

    @property
    def notifications_refuse_for_proxy(self):
        return job_application_notifications.JobApplicationRefusedForProxyNotification(
            self.sender,
            self.sender_prescriber_organization or self.sender_company,
            job_application=self,
        )

    @property
    def notifications_refuse_for_job_seeker(self):
        return job_application_notifications.JobApplicationRefusedForJobSeekerNotification(
            self.job_seeker,
            job_application=self,
        )

    def notifications_cancel_for_employer(self, canceled_by):
        return job_application_notifications.JobApplicationCanceledNotification(
            canceled_by,
            self.to_company,
            job_application=self,
        )

    @property
    def notifications_cancel_for_proxy(self):
        return job_application_notifications.JobApplicationCanceledNotification(
            self.sender,
            self.sender_prescriber_organization or self.sender_company,
            job_application=self,
        )

    def notifications_deliver_approval(self, accepted_by):
        return PassAcceptedEmployerNotification(
            accepted_by,
            self.to_company,
            job_application=self,
            siae_survey_link=self.to_company.accept_survey_url,
        )

    def notifications_transfer_for_previous_employer(self, previous_employer, notification_context):
        return job_application_notifications.JobApplicationTransferredForEmployerNotification(
            previous_employer,
            self.transferred_from,
            **notification_context,
        )

    def notifications_transfer_for_job_seeker(self, notification_context):
        return job_application_notifications.JobApplicationTransferredForJobSeekerNotification(
            self.job_seeker,
            **notification_context,
        )

    def notifications_transfer_for_proxy(self, notification_context):
        return job_application_notifications.JobApplicationTransferredForPrescriberNotification(
            self.sender,
            self.sender_prescriber_organization,
            **notification_context,
        )

    # Emails
    def email_manual_approval_delivery_required_notification(self, accepted_by):
        to = [settings.ITOU_EMAIL_CONTACT]
        context = {
            "job_application": self,
            "admin_manually_add_approval_url": get_absolute_url(
                reverse("admin:approvals_approval_manually_add_approval", args=[self.pk])
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
        context = {
            "job_application": self,
            "job_application_url": get_absolute_url(
                reverse("apply:details_for_company", kwargs={"job_application_id": self.pk})
            ),
            "search_url": get_absolute_url(reverse("search:prescribers_home")),
        }
        subject = "approvals/email/refuse_manually_subject.txt"
        body = "approvals/email/refuse_manually_body.txt"
        return get_email_message(to, context, subject, body)

    @property
    def email_diagoriente_invite_for_prescriber(self):
        to = [self.sender.email]
        subject = "apply/email/diagoriente_prescriber_invite_subject.txt"
        body = "apply/email/diagoriente_prescriber_invite_body.txt"
        context = {"job_application": self}
        return get_email_message(to, context, subject, body)

    @property
    def email_diagoriente_invite_for_job_seeker(self):
        to = [self.sender.email]
        subject = "apply/email/diagoriente_job_seeker_invite_subject.txt"
        body = "apply/email/diagoriente_job_seeker_invite_body.txt"
        context = {"job_application": self}
        return get_email_message(to, context, subject, body)


class JobApplicationTransitionLog(xwf_models.BaseTransitionLog):
    """
    JobApplication's transition logs are stored in this table.
    https://django-xworkflows.readthedocs.io/en/latest/internals.html#django_xworkflows.models.BaseTransitionLog
    """

    MODIFIED_OBJECT_FIELD = "job_application"
    EXTRA_LOG_ATTRIBUTES = (
        ("user", "user", None),
        ("target_company", "target_company", None),  # used in external transfer and transfer
    )
    job_application = models.ForeignKey(JobApplication, related_name="logs", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    target_company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise destinataire",
        on_delete=models.SET_NULL,
        related_name="job_application_log_transfers",
        null=True,
    )

    class Meta:
        verbose_name = "log des transitions de la candidature"
        verbose_name_plural = "log des transitions des candidatures"
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.id)

    @property
    def pretty_to_state(self):
        choices = dict(JobApplicationState.choices)
        return choices[self.to_state]


class PriorAction(models.Model):
    job_application = models.ForeignKey(JobApplication, related_name="prior_actions", on_delete=models.CASCADE)
    action = models.TextField(
        verbose_name="action",
        choices=[
            ("Mise en situation professionnelle", ProfessionalSituationExperience.choices),
            ("Pré-qualification", Prequalification.choices),
        ],
    )
    dates = InclusiveDateRangeField(verbose_name="dates")

    @property
    def action_kind(self):
        if self.action in ProfessionalSituationExperience.values:
            return "Mise en situation professionnelle"
        elif self.action in Prequalification.values:
            return "Pré-qualification"
        return "Inconnu"
