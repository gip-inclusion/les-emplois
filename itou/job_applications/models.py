import datetime
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, Count, Exists, F, Max, OuterRef, Prefetch, Q, Subquery, When
from django.db.models.functions import Coalesce, Greatest, TruncMonth
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.models import Approval, Prolongation, Suspension
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS, CompanyKind, ContractType
from itou.companies.models import Company
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models import EligibilityDiagnosis, SelectedAdministrativeCriteria
from itou.employee_record import enums as employeerecord_enums
from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.enums import (
    GEIQ_MAX_HOURS_PER_WEEK,
    GEIQ_MIN_HOURS_PER_WEEK,
    Origin,
    Prequalification,
    ProfessionalSituationExperience,
    QualificationLevel,
    QualificationType,
    RefusalReason,
    SenderKind,
)
from itou.users.enums import LackOfPoleEmploiId, UserKind
from itou.utils.emails import get_email_message, send_email_messages
from itou.utils.models import InclusiveDateRangeField
from itou.utils.urls import get_absolute_url


class JobApplicationWorkflow(xwf_models.Workflow):
    """
    The JobApplication workflow.
    https://django-xworkflows.readthedocs.io/
    """

    STATE_NEW = "new"
    STATE_PROCESSING = "processing"
    STATE_POSTPONED = "postponed"
    STATE_PRIOR_TO_HIRE = "prior_to_hire"
    STATE_ACCEPTED = "accepted"
    STATE_REFUSED = "refused"
    STATE_CANCELLED = "cancelled"
    # When a job application is accepted, all other job seeker's pending applications become obsolete.
    STATE_OBSOLETE = "obsolete"

    STATE_CHOICES = (
        (STATE_NEW, "Nouvelle candidature"),
        (STATE_PROCESSING, "Candidature à l'étude"),
        (STATE_POSTPONED, "Candidature en attente"),
        (STATE_PRIOR_TO_HIRE, "Action préalable à l’embauche"),
        (STATE_ACCEPTED, "Candidature acceptée"),
        (STATE_REFUSED, "Candidature déclinée"),
        (STATE_CANCELLED, "Embauche annulée"),
        (STATE_OBSOLETE, "Embauché ailleurs"),
    )

    states = STATE_CHOICES

    TRANSITION_PROCESS = "process"
    TRANSITION_POSTPONE = "postpone"
    TRANSITION_ACCEPT = "accept"
    TRANSITION_MOVE_TO_PRIOR_TO_HIRE = "move_to_prior_to_hire"
    TRANSITION_CANCEL_PRIOR_TO_HIRE = "cancel_prior_to_hire"
    TRANSITION_REFUSE = "refuse"
    TRANSITION_CANCEL = "cancel"
    TRANSITION_RENDER_OBSOLETE = "render_obsolete"
    TRANSITION_TRANSFER = "transfer"

    TRANSITION_CHOICES = (
        (TRANSITION_PROCESS, "Étudier la candidature"),
        (TRANSITION_POSTPONE, "Reporter la candidature"),
        (TRANSITION_ACCEPT, "Accepter la candidature"),
        (TRANSITION_MOVE_TO_PRIOR_TO_HIRE, "Passer en pré-embauche"),
        (TRANSITION_CANCEL_PRIOR_TO_HIRE, "Annuler la pré-embauche"),
        (TRANSITION_REFUSE, "Décliner la candidature"),
        (TRANSITION_CANCEL, "Annuler la candidature"),
        (TRANSITION_RENDER_OBSOLETE, "Rendre obsolete la candidature"),
        (TRANSITION_TRANSFER, "Transfert de la candidature vers une autre SIAE"),
    )

    CAN_BE_ACCEPTED_STATES = [
        STATE_PROCESSING,
        STATE_POSTPONED,
        STATE_PRIOR_TO_HIRE,
        STATE_OBSOLETE,
        STATE_REFUSED,
        STATE_CANCELLED,
    ]
    CAN_BE_TRANSFERRED_STATES = CAN_BE_ACCEPTED_STATES
    CAN_ADD_PRIOR_ACTION_STATES = [STATE_PROCESSING, STATE_POSTPONED, STATE_OBSOLETE, STATE_REFUSED, STATE_CANCELLED]

    transitions = (
        (TRANSITION_PROCESS, STATE_NEW, STATE_PROCESSING),
        (TRANSITION_POSTPONE, [STATE_PROCESSING, STATE_PRIOR_TO_HIRE], STATE_POSTPONED),
        (TRANSITION_ACCEPT, CAN_BE_ACCEPTED_STATES, STATE_ACCEPTED),
        (TRANSITION_MOVE_TO_PRIOR_TO_HIRE, CAN_ADD_PRIOR_ACTION_STATES, STATE_PRIOR_TO_HIRE),
        (TRANSITION_CANCEL_PRIOR_TO_HIRE, [STATE_PRIOR_TO_HIRE], STATE_PROCESSING),
        (TRANSITION_REFUSE, [STATE_NEW, STATE_PROCESSING, STATE_PRIOR_TO_HIRE, STATE_POSTPONED], STATE_REFUSED),
        (TRANSITION_CANCEL, STATE_ACCEPTED, STATE_CANCELLED),
        (TRANSITION_RENDER_OBSOLETE, [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED], STATE_OBSOLETE),
        (TRANSITION_TRANSFER, CAN_BE_TRANSFERRED_STATES, STATE_NEW),
    )

    PENDING_STATES = [STATE_NEW, STATE_PROCESSING, STATE_POSTPONED]
    initial_state = STATE_NEW

    log_model = "job_applications.JobApplicationTransitionLog"


class JobApplicationQuerySet(models.QuerySet):
    def is_active_company_member(self, user):
        return self.filter(to_company__members=user, to_company__members__is_active=True)

    def pending(self):
        return self.filter(state__in=JobApplicationWorkflow.PENDING_STATES)

    def accepted(self):
        return self.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    def not_archived(self):
        """
        Filters out the archived job_applications
        """
        return self.exclude(hidden_for_company=True)

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
                # Mega Super duper special case to handle job applications created to generate AI's PASS IAE
                When(
                    origin=Origin.AI_STOCK,
                    then=F("hiring_start_at"),
                ),
                When(origin=Origin.PE_APPROVAL, then=F("created_at")),
                When(
                    state=JobApplicationWorkflow.STATE_ACCEPTED,
                    # A job_application created at the accepted status will
                    # not have transitions logs, fallback on created_at
                    then=Coalesce(created_at_from_transition, F("created_at")),
                ),
                default=created_at_from_transition,
                output_field=models.DateTimeField(),
            )
        )

    def with_jobseeker_eligibility_diagnosis(self):
        """
        Gives the "eligibility_diagnosis" linked to the job application or if none is found
        the last eligibility diagnosis for jobseeker
        """
        sub_query = Subquery(
            (
                EligibilityDiagnosis.objects.filter(job_seeker=OuterRef("job_seeker"))
                .order_by("-created_at")
                .values("id")[:1]
            ),
            output_field=models.IntegerField(),
        )
        return self.annotate(jobseeker_eligibility_diagnosis=Coalesce(F("eligibility_diagnosis"), sub_query, None))

    def eligibility_validated(self):
        return self.filter(
            Exists(
                Approval.objects.filter(
                    user=OuterRef("job_seeker"),
                ).valid()
            )
            | Exists(
                EligibilityDiagnosis.objects.for_job_seeker_and_siae(
                    job_seeker=OuterRef("job_seeker"), siae=OuterRef("to_company")
                ).valid()
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

    # Employee record querysets

    def _eligible_job_applications_with_employee_record(self, siae):
        """
        Eligible job applications with a `NEW` employee record,

        Not a public API: use `eligible_as_employee_record`.
        """
        return self.filter(
            to_company=siae,
            employee_record__status=employeerecord_enums.Status.NEW,
        )

    def _eligible_job_applications_without_employee_record(self, siae):
        """
        Eligible job applications without any employee records linked.

        Not a public API: use `eligible_as_employee_record`.
        """
        return self.accepted().filter(
            # Must be linked to an approval
            approval__isnull=False,
            # Only for that SIAE
            to_company=siae,
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
                        siae=OuterRef("to_company"),
                        approval=OuterRef("approval"),
                        created_at__gte=EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
                    )
                ),
                has_recent_prolongation=Exists(
                    Prolongation.objects.filter(
                        declared_by_siae=OuterRef("to_company"),
                        approval=OuterRef("approval"),
                        created_at__gte=EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE,
                    )
                ),
            )
            .filter(
                # Must be linked to an approval with a Suspension or a Prolongation
                # Bypass the `create_employee_record` flag for Prolongation because:
                # - Job applications created for the AI stock all have the flag, but we need to send the new end date.
                # - Enabling it for Suspension will create *a lot* of "FS actualisation" which will create a lot of
                #   messages to the support, like when we introduced them the first time.
                # - Prolongation will always block the employer, it's a much rarer case for Suspension.
                Q(has_recent_suspension=True, create_employee_record=True) | Q(has_recent_prolongation=True),
                # Only for that SIAE
                to_company=siae,
                # There must be **NO** employee record linked in this part
                employee_record__isnull=True,
            )
        )

    def eligible_as_employee_record(self, siae):
        """
        Get a list of job applications potentially "updatable" as an employee record.
        For display concerns (list of employee records for a given SIAE).

        Rules of eligibility for a job application:
            - be in 'ACCEPTED' state (valid hiring)
            - to be linked to an approval
            - hiring SIAE must be one of : ACI, AI, EI, ETTI.
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
        if siae.kind not in Company.ASP_EMPLOYEE_RECORD_KINDS:
            return self.none()

        eligible_job_applications = JobApplicationQuerySet.union(
            self._eligible_job_applications_with_employee_record(siae),
            self._eligible_job_applications_without_employee_record(siae),
            self._eligible_job_applications_with_a_suspended_or_extended_approval(siae),
        )

        # Return the approvals already used by any SIAE of the convention
        approvals_to_exclude = (
            EmployeeRecord.objects.for_asp_company(siae)
            # We need to exclude NEW employee records otherwise we are shooting ourselves in the foot by excluding
            # job applications selected in `._eligible_job_applications_with_employee_record()`
            .exclude(status__in=[employeerecord_enums.Status.NEW]).values("approval_number")
        )

        # TIP: you can't filter on a UNION of querysets,
        # but you can convert it as a subquery and then order and filter it
        return (
            self.filter(pk__in=eligible_job_applications.values("id"))
            .exclude(approval__number__in=approvals_to_exclude)
            .select_related("approval", "job_seeker__jobseeker_profile")
            .prefetch_related("employee_record")
            .order_by("-hiring_start_at")
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
        verbose_name="demandeur d'emploi",
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
        verbose_name="diagnostic d'éligibilité",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    geiq_eligibility_diagnosis = models.ForeignKey(
        "eligibility.GEIQEligibilityDiagnosis",
        verbose_name="diagnostic d'éligibilité GEIQ",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_applications",
    )

    # Exclude flagged approvals (batch creation or import of approvals).
    # See itou.users.management.commands.import_ai_employees.
    create_employee_record = models.BooleanField(default=True, verbose_name="création d'une fiche salarié")

    # The job seeker's resume used for this job application.
    # TODO: Remove the patchy code block of the `test_bucket` fixture when this field become a ForeignKey()
    resume_link = models.URLField(max_length=500, verbose_name="lien vers un CV", blank=True)

    # Who send the job application. It can be the same user as `job_seeker`
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur émetteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_applications_sent",
    )

    sender_kind = models.CharField(
        verbose_name="type de l'émetteur",
        max_length=10,
        choices=SenderKind.choices,
        default=SenderKind.PRESCRIBER,
    )

    # When the sender is an employer, keep a track of his current company.
    sender_company = models.ForeignKey(
        "companies.Company", verbose_name="entreprise émettrice", null=True, blank=True, on_delete=models.CASCADE
    )

    # When the sender is a prescriber, keep a track of his current organization (if any).
    sender_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation du prescripteur émettrice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    to_company = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise destinataire",
        on_delete=models.CASCADE,
        related_name="job_applications_received",
    )

    state = xwf_models.StateField(JobApplicationWorkflow, verbose_name="état", db_index=True)

    # Jobs in which the job seeker is interested (optional).
    selected_jobs = models.ManyToManyField("companies.JobDescription", verbose_name="métiers recherchés", blank=True)
    # Job for which the job seeker was hired (may not be among selected_jobs)
    hired_job = models.ForeignKey(
        "companies.JobDescription",
        verbose_name="poste retenu",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="hired_job_applications",
    )

    message = models.TextField(verbose_name="message de candidature", blank=True)
    answer = models.TextField(verbose_name="message de réponse", blank=True)
    answer_to_prescriber = models.TextField(verbose_name="message de réponse au prescripteur", blank=True)
    refusal_reason = models.CharField(
        verbose_name="motifs de refus", max_length=30, choices=RefusalReason.choices, blank=True
    )

    hiring_start_at = models.DateField(verbose_name="date de début du contrat", blank=True, null=True, db_index=True)
    hiring_end_at = models.DateField(verbose_name="date prévisionnelle de fin du contrat", blank=True, null=True)

    hiring_without_approval = models.BooleanField(
        default=False, verbose_name="l'entreprise choisit de ne pas obtenir un PASS IAE à l'embauche"
    )

    origin = models.CharField(
        verbose_name="origine de la candidature", max_length=30, choices=Origin.choices, default=Origin.DEFAULT
    )

    # Job applications sent to SIAEs subject to eligibility rules can obtain an
    # Approval after being accepted.
    approval = models.ForeignKey(
        "approvals.Approval", verbose_name="PASS IAE", null=True, blank=True, on_delete=models.SET_NULL
    )
    approval_delivery_mode = models.CharField(
        verbose_name="mode d'attribution du PASS IAE",
        max_length=30,
        choices=APPROVAL_DELIVERY_MODE_CHOICES,
        blank=True,
    )
    # Fields used for approvals processed both manually or automatically.
    approval_number_sent_by_email = models.BooleanField(verbose_name="PASS IAE envoyé par email", default=False)
    approval_number_sent_at = models.DateTimeField(
        verbose_name="date d'envoi du PASS IAE", blank=True, null=True, db_index=True
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
        verbose_name="date de refus manuel du PASS IAE", blank=True, null=True
    )

    hidden_for_company = models.BooleanField(default=False, verbose_name="masqué coté employeur")

    transferred_at = models.DateTimeField(verbose_name="date de transfert", null=True, blank=True)
    transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="transférée par", null=True, blank=True, on_delete=models.SET_NULL
    )
    transferred_from = models.ForeignKey(
        "companies.Company",
        verbose_name="entreprise d'origine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_application_transferred",
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)

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
                check=models.Q(
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
                check=~models.Q(eligibility_diagnosis__isnull=False, geiq_eligibility_diagnosis__isnull=False),
            ),
            models.CheckConstraint(
                name="qualification_coherence",
                violation_error_message="Incohérence dans les champs concernant la qualification pour le contrat GEIQ",
                check=~models.Q(
                    qualification_level=QualificationLevel.NOT_RELEVANT,
                    qualification_type=QualificationType.STATE_DIPLOMA,
                ),
            ),
        ]

    def __str__(self):
        return str(self.id)

    def clean(self):
        super().clean()

        # We have severals cases of job_applications on job_seekers or employer
        # We don't know how it happened, so we'll just add a sanity check here
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

    def save(self, *args, **kwargs):
        self.full_clean()
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
        return self.to_company.is_subject_to_eligibility_rules and not self.job_seeker.has_valid_diagnosis(
            for_siae=self.to_company
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
    def refused_by(self):
        if self.state.is_refused and (
            last_log := self.logs.select_related("user").filter(to_state=JobApplicationWorkflow.STATE_REFUSED).last()
        ):
            return last_log.user

    @property
    def can_be_cancelled(self):
        if self.origin == Origin.AI_STOCK:
            return False
        if not self.employee_record.exists():
            # A job application can be canceled provided that there is no employee record linked to it,
            # as it is possible that some information were already sent to the ASP.
            return True
        return False

    @property
    def can_be_archived(self):
        return self.state in [
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

    @property
    def can_have_prior_action(self):
        return self.to_company.can_have_prior_action and not self.state.is_new

    @property
    def can_change_prior_actions(self):
        return self.can_have_prior_action and not self.state.is_accepted

    @property
    def is_refused_due_to_deactivation(self):
        return (
            self.state == JobApplicationWorkflow.STATE_REFUSED
            and self.refusal_reason == RefusalReason.DEACTIVATION.value
        )

    @property
    def is_refused_for_other_reason(self):
        return self.state.is_refused and self.refusal_reason == RefusalReason.OTHER

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
        elif self.sender_kind == SenderKind.EMPLOYER and self.to_company.kind not in SIAE_WITH_CONVENTION_KINDS:
            # Not an SIAE per se
            return "Employeur"
        else:
            return SenderKind(self.sender_kind).label

    @property
    def is_in_transferable_state(self):
        return self.state != JobApplicationWorkflow.STATE_ACCEPTED

    def can_be_transferred(self, user, target_company):
        # User must be member of both origin and target companies to make a transfer
        if not (self.to_company.has_member(user) and target_company.has_member(user)):
            return False
        # Can't transfer to same structure
        if target_company == self.to_company:
            return False
        if not user.is_employer:
            return False
        return self.is_in_transferable_state

    def transfer_to(self, transferred_by, target_company):
        if not (self.is_in_transferable_state and self.can_be_transferred(transferred_by, target_company)):
            raise ValidationError(
                f"Cette candidature n'est pas transferable ({transferred_by=}, {target_company=}, {self.to_company=})"
            )

        self.transferred_from = self.to_company
        self.transferred_by = transferred_by
        self.transferred_at = timezone.now()
        self.to_company = target_company
        self.state = JobApplicationWorkflow.STATE_NEW
        # Consider job application as new : don't keep answers
        self.answer = self.answer_to_prescriber = ""

        # Delete eligibility diagnosis if not provided by an authorized prescriber
        eligibility_diagnosis = self.eligibility_diagnosis
        is_eligibility_diagnosis_made_by_siae = (
            eligibility_diagnosis and eligibility_diagnosis.author_kind == AuthorKind.EMPLOYER
        )
        if is_eligibility_diagnosis_made_by_siae:
            self.eligibility_diagnosis = None

        self.save(
            update_fields=[
                "eligibility_diagnosis",
                "to_company",
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
            self.get_email_transfer_origin_company(transferred_by, self.transferred_from, target_company),
            self.get_email_transfer_job_seeker(transferred_by, self.transferred_from, target_company),
        ]

        # Send email to prescriber or orienter if any
        if self.sender_kind == SenderKind.PRESCRIBER and self.sender_id:  # Sender user may have been deleted.
            emails.append(self.get_email_transfer_prescriber(transferred_by, self.transferred_from, target_company))

        send_email_messages(emails)

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
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            emails.append(self.email_accept_for_proxy)

        # Link to the job seeker's eligibility diagnosis.
        if self.to_company.is_subject_to_eligibility_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, for_siae=self.to_company
            )

        # Approval issuance logic.
        if not self.hiring_without_approval and self.to_company.is_subject_to_eligibility_rules:
            if self.job_seeker.has_common_approval_in_waiting_period:
                if self.job_seeker.approval_can_be_renewed_by(
                    siae=self.to_company, sender_prescriber_organization=self.sender_prescriber_organization
                ):
                    # Security check: it's supposed to be blocked upstream.
                    raise xwf_models.AbortTransition("Job seeker has an approval in waiting period.")

            if self.job_seeker.has_valid_common_approval:
                # Automatically reuse an existing valid Itou or PE approval.
                self.approval = self.job_seeker.get_or_create_approval(origin_job_application=self)
                if self.approval.start_at > self.hiring_start_at:
                    # As a job seeker can have multiple contracts at the same time,
                    # the approval should start at the same time as most recent contract.
                    self.approval.update_start_date(new_start_date=self.hiring_start_at)
                emails.append(self.email_deliver_approval(accepted_by))
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
                    raise xwf_models.AbortTransition("Cannot create an approval without eligibility diagnosis here")
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
                emails.append(self.email_deliver_approval(accepted_by))
            elif not self.job_seeker.jobseeker_profile.nir or (
                not self.job_seeker.jobseeker_profile.pole_emploi_id
                and self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
                == LackOfPoleEmploiId.REASON_FORGOTTEN
            ):
                # Trigger a manual approval creation.
                self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_MANUAL
                emails.append(self.email_manual_approval_delivery_required_notification(accepted_by))
            else:
                raise xwf_models.AbortTransition("Job seeker has an invalid PE status, cannot issue approval.")

        # Send emails in batch.
        send_email_messages(emails)

        if self.approval:
            self.approval_number_sent_by_email = True
            self.approval_number_sent_at = timezone.now()
            self.approval_delivery_mode = self.APPROVAL_DELIVERY_MODE_AUTOMATIC
            self.approval.unsuspend(self.hiring_start_at)

    @xwf_models.transition()
    def refuse(self, *args, **kwargs):
        # Send notification.
        emails = [self.email_refuse_for_job_seeker]
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
            emails.append(self.email_refuse_for_proxy)
        send_email_messages(emails)

    @xwf_models.transition()
    def cancel(self, *args, **kwargs):
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
        if self.is_sent_by_proxy and self.sender_id:  # Sender user may have been deleted.
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
        context = {"job_application": self, "siae_survey_link": self.to_company.accept_survey_url}
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

    def _get_transfer_email(self, to, subject, body, transferred_by, origin_company, target_company):
        context = {
            "job_application": self,
            "transferred_by": transferred_by,
            "origin_company": origin_company,
            "target_company": target_company,
        }
        return get_email_message(to, context, subject, body)

    def get_email_transfer_origin_company(self, transferred_by, origin_company, target_company):
        # Send email to every active member of the origin company
        to = list(origin_company.active_members.values_list("email", flat=True))
        subject = "apply/email/transfer_origin_company_subject.txt"
        body = "apply/email/transfer_origin_company_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_company, target_company)

    def get_email_transfer_job_seeker(self, transferred_by, origin_company, target_company):
        to = [self.job_seeker.email]
        subject = "apply/email/transfer_job_seeker_subject.txt"
        body = "apply/email/transfer_job_seeker_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_company, target_company)

    def get_email_transfer_prescriber(self, transferred_by, origin_company, target_company):
        to = [self.sender.email]
        subject = "apply/email/transfer_prescriber_subject.txt"
        body = "apply/email/transfer_prescriber_body.txt"

        return self._get_transfer_email(to, subject, body, transferred_by, origin_company, target_company)

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
        verbose_name = "log des transitions de la candidature"
        verbose_name_plural = "log des transitions des candidatures"
        ordering = ["-timestamp"]

    def __str__(self):
        return str(self.id)

    @property
    def pretty_to_state(self):
        choices = dict(JobApplicationWorkflow.STATE_CHOICES)
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
