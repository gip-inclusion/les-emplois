import enum

import xworkflows
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Exists, F, Max, OuterRef, Subquery
from django.db.models.functions import Greatest
from django.db.models.manager import Manager
from django.db.models.query import Q, QuerySet
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.models import Approval
from itou.asp.models import EmployerType, PrescriberType, SiaeMeasure
from itou.companies.models import Company, SiaeFinancialAnnex
from itou.employee_record.enums import MovementType, NotificationStatus, Status
from itou.job_applications.enums import SenderKind
from itou.utils.validators import validate_siret


# Validators


def validate_asp_batch_filename(value):
    """
    Simple validation of batch file name
    (ASP backend is picky about it)
    """
    if value and value.startswith("RIAE_FS_") and value.endswith(".json") and len(value) == 27:
        return
    raise ValidationError(f"Le format du nom de fichier ASP est incorrect: {value}")


class ASPExchangeInformation(models.Model):
    ASP_PROCESSING_SUCCESS_CODE = "0000"
    ASP_DUPLICATE_ERROR_CODE = "3436"

    ASP_MOVEMENT_TYPE = None  # Must be specified in descendant classes

    # ASP processing part
    asp_processing_code = models.CharField(max_length=4, verbose_name="code de traitement ASP", null=True)
    asp_processing_label = models.CharField(max_length=200, verbose_name="libellé de traitement ASP", null=True)

    # Employee records are sent to ASP in a JSON file,
    # We keep track of the name for processing feedback
    # The format of the file name is EXACTLY: RIAE_FS_AAAAMMJJHHMMSS.json (27 chars)
    asp_batch_file = models.CharField(
        max_length=27,
        verbose_name="fichier de batch ASP",
        null=True,
        validators=[validate_asp_batch_filename],
    )
    # Line number of the employee record in the batch file
    # Unique pair with `asp_batch_file`
    asp_batch_line_number = models.IntegerField(
        verbose_name="ligne correspondante dans le fichier batch ASP",
        null=True,
    )

    # Once correctly processed by ASP, the employee record is archived:
    # - it can't be changed anymore
    # - a serialized version of the employee record is stored (as proof, and for API concerns)
    # The API will not use JSON serializers on a regular basis,
    # except for the archive serialization, which occurs once.
    # It will only return a list of this JSON field for archived employee records.
    archived_json = models.JSONField(verbose_name="archive JSON de la fiche salarié", null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=["asp_batch_file", "asp_batch_line_number"],
                name="unique_%(class)s_asp_batch_file_and_line",
                condition=Q(asp_batch_file__isnull=False),
            )
        ]
        ordering = ["-created_at"]

    def set_asp_batch_information(self, file, line_number, archive):
        self.asp_batch_file = file
        self.asp_batch_line_number = line_number
        self.archived_json = archive

    def set_asp_processing_information(self, code, label, archive):
        self.asp_processing_code = code
        self.asp_processing_label = label
        self.archived_json = archive


class EmployeeRecordTransition(enum.StrEnum):
    READY = "ready"
    WAIT_FOR_ASP_RESPONSE = "wait_for_asp_response"
    REJECT = "reject"
    PROCESS = "process"
    DISABLE = "disable"
    ENABLE = "enable"
    ARCHIVE = "archive"
    UNARCHIVE_NEW = "unarchive_new"
    UNARCHIVE_PROCESSED = "unarchive_processed"
    UNARCHIVE_REJECTED = "unarchive_rejected"

    @classmethod
    def without_asp_exchange(cls):
        return {
            cls.READY,
            cls.DISABLE,
            cls.ENABLE,
            cls.ARCHIVE,
            cls.UNARCHIVE_NEW,
        }


class EmployeeRecordWorkflow(xwf_models.Workflow):
    states = Status.choices
    initial_state = Status.NEW

    CAN_BE_DISABLED_STATES = [Status.NEW, Status.REJECTED, Status.PROCESSED]
    CAN_BE_ARCHIVED_STATES = [Status.NEW, Status.READY, Status.REJECTED, Status.PROCESSED, Status.DISABLED]
    transitions = (
        (
            EmployeeRecordTransition.READY,
            [Status.NEW, Status.REJECTED, Status.DISABLED, Status.PROCESSED],
            Status.READY,
        ),
        (EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE, Status.READY, Status.SENT),
        (EmployeeRecordTransition.REJECT, Status.SENT, Status.REJECTED),
        (EmployeeRecordTransition.PROCESS, Status.SENT, Status.PROCESSED),
        (EmployeeRecordTransition.DISABLE, CAN_BE_DISABLED_STATES, Status.DISABLED),
        (EmployeeRecordTransition.ENABLE, Status.DISABLED, Status.NEW),
        (EmployeeRecordTransition.ARCHIVE, CAN_BE_ARCHIVED_STATES, Status.ARCHIVED),
        (EmployeeRecordTransition.UNARCHIVE_NEW, Status.ARCHIVED, Status.NEW),
        (EmployeeRecordTransition.UNARCHIVE_PROCESSED, Status.ARCHIVED, Status.PROCESSED),
        (EmployeeRecordTransition.UNARCHIVE_REJECTED, Status.ARCHIVED, Status.REJECTED),
    )
    log_model = "employee_record.EmployeeRecordTransitionLog"


class EmployeeRecordQuerySet(models.QuerySet):
    def full_fetch(self):
        return self.select_related(
            "financial_annex",
            "job_application",
            "job_application__approval",
            "job_application__to_company",
            "job_application__to_company__convention",
            "job_application__job_seeker",
            "job_application__job_seeker__jobseeker_profile__birth_country",
            "job_application__job_seeker__jobseeker_profile__birth_place",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__job_seeker__jobseeker_profile__hexa_commune",
            "job_application__sender_prescriber_organization",
        )

    # Search queries
    def for_company(self, siae):
        return self.filter(job_application__to_company=siae)

    def for_asp_company(self, siae):
        return self.filter(job_application__to_company__in=siae.convention.siaes.all())

    def find_by_batch(self, filename, line_number):
        """
        Fetch a single employee record with ASP batch file input parameters
        """
        return self.filter(asp_batch_file=filename, asp_batch_line_number=line_number)

    def archivable(self):
        return (
            self.annotate(
                approval_is_valid=Exists(Approval.objects.filter(number=OuterRef("approval_number")).valid())
            )
            .exclude(
                status=Status.ARCHIVED,
            )
            .filter(
                approval_is_valid=False,
                created_at__lt=timezone.now() - relativedelta(months=6),  # 6-months grace period if recently created
                updated_at__lt=timezone.now() - relativedelta(months=1),  # 1-month grace period if recently updated
            )
        )

    def missed_notifications(self):
        return self.annotate(
            last_employee_record_snapshot=Greatest(
                # We take `updated_at` and not `created_at` to mimic how the trigger would have behaved if the
                # employee record was never ARCHIVED. For exemple, if the ER was DISABLED before ARCHIVED then no
                # notification would have been sent, the trigger ask for a PROCESSED, if a prolongation was
                # submitted between those two events.
                F("updated_at"),
                Max(F("update_notifications__created_at")),
            ),
        ).filter(
            last_employee_record_snapshot__lt=F("job_application__approval__updated_at"),
        )

    def with_siret_from_asp_source(self):
        return self.annotate(
            siret_from_asp_source=Subquery(
                Company.objects.filter(
                    source=Company.SOURCE_ASP, convention=OuterRef("job_application__to_company__convention")
                ).values("siret")
            )
        )


class EmployeeRecord(ASPExchangeInformation, xwf_models.WorkflowEnabled):
    """
    EmployeeRecord - Fiche salarié (FS for short)

    Holds information needed for JSON exports and processing by ASP
    """

    ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED = "La candidature doit être acceptée"
    ERROR_JOB_APPLICATION_WITHOUT_APPROVAL = "L'embauche n'est pas reliée à un PASS IAE"

    ERROR_EMPLOYEE_RECORD_IS_DUPLICATE = "Une fiche salarié pour ce PASS IAE et cette SIAE existe déjà"
    ERROR_EMPLOYEE_RECORD_INVALID_STATE = "La fiche salarié n'est pas dans l'état requis pour cette action"

    ERROR_NO_CONVENTION_AVAILABLE = "La structure actuelle ne dispose d'aucune convention"

    ASP_MOVEMENT_TYPE = MovementType.CREATION

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    processed_at = models.DateTimeField(verbose_name="date d'intégration", null=True)
    status = xwf_models.StateField(EmployeeRecordWorkflow, verbose_name="statut", max_length=10)

    # Job application has references on many mandatory parts of the E.R.:
    # - SIAE / asp id
    # - Employee
    # - Approval
    job_application = models.ForeignKey(
        "job_applications.JobApplication",
        on_delete=models.RESTRICT,
        verbose_name="candidature / embauche",
        related_name="employee_record",
    )

    # Employee records may be linked to a valid financial annex
    # This field can't be automatically filled, the user will be asked
    # to select a valid one manually
    financial_annex = models.ForeignKey(
        SiaeFinancialAnnex, verbose_name="annexe financière", null=True, on_delete=models.SET_NULL
    )

    # These fields are duplicated to act as constraint fields on DB level
    approval_number = models.CharField(max_length=12, verbose_name="numéro d'agrément")
    asp_id = models.PositiveIntegerField(verbose_name="identifiant ASP de la SIAE")  # TODO(rsebille): Remove it.
    asp_measure = models.CharField(verbose_name="mesure ASP de la SIAE", choices=SiaeMeasure.choices)

    # If the SIAE is an "antenna",
    # we MUST provide the SIRET of the SIAE linked to the financial annex on ASP side (i.e. "parent/mother" SIAE)
    # NOT the actual SIAE (which can be fake and unrecognized by ASP).
    siret = models.CharField(
        verbose_name="siret structure mère", max_length=14, validators=[validate_siret], db_index=True
    )

    # When an employee record is rejected with a '3436' error code by ASP, it means that:
    # - all the information transmitted via this employee record is already available on ASP side,
    # - the employee record is not needed by ASP and considered as a duplicate
    # As a result, employee records in `REJECTED` state and with a `3436` error code
    # can safely be considered as `PROCESSED` without side-effects.
    # This field is just a marker / reminder / track record that the status of this object
    # was **forced** to `PROCESSED` (via admin or script) even if originally `REJECTED`.
    # The JSON proof is in this case not available.
    # Forcing a 'PROCESSED' status enables communication for employee record update notifications.
    processed_as_duplicate = models.BooleanField(verbose_name="déjà intégrée par l'ASP", default=False)

    # Added typing helper: improved type checking for `objects` methods
    objects: EmployeeRecordQuerySet | Manager = EmployeeRecordQuerySet.as_manager()

    class Meta(ASPExchangeInformation.Meta):
        verbose_name = "fiche salarié"
        verbose_name_plural = "fiches salarié"
        constraints = ASPExchangeInformation.Meta.constraints + [
            models.UniqueConstraint(
                fields=["asp_measure", "siret", "approval_number"],
                name="unique_asp_measure_siret_approval_number",
            ),
        ]

    def __str__(self):
        return (
            f"PK:{self.pk} PASS:{self.approval_number} SIRET:{self.siret} JA:{self.job_application_id} "
            f"JOBSEEKER:{self.job_application.job_seeker_id} STATUS:{self.status}"
        )

    def _clean_job_application(self):
        """
        Check if job application is valid for FS
        """
        if not self.job_application.to_company.convention:
            raise ValidationError(self.ERROR_NO_CONVENTION_AVAILABLE)

        if not self.job_application.state.is_accepted:
            raise ValidationError(self.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED)

        if not self.job_application.approval:
            raise ValidationError(self.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL)

    def _clean_job_seeker(self):
        """
        Check if data provided for the job seeker part of the FS is complete / valid
        """
        job_seeker = self.job_application.job_seeker

        # Check if user is "clean"
        job_seeker.clean()

        # Further validation in the job seeker profile
        # Note that the job seeker profile validation is done
        # via `clean_model` and not `clean` : see comments on `JobSeekerProfile.clean_model`
        job_seeker.jobseeker_profile.clean_model()

    def clean(self):
        # see private methods above
        self._clean_job_application()
        self._clean_job_seeker()

    def _fill_denormalized_fields(self):
        # If the SIAE is an antenna, the SIRET will be rejected by the ASP so we have to use the mother's one
        self.siret = self.job_application.to_company.siret_from_asp_source()
        self.asp_id = self.job_application.to_company.convention.asp_id
        self.asp_measure = SiaeMeasure.from_siae_kind(self.job_application.to_company.kind)
        self.approval_number = self.job_application.approval.number

    # Business methods

    @xwf_models.transition()
    def ready(self, *, user=None):
        """
        Prepare the employee record for transmission
        """
        profile = self.job_application.job_seeker.jobseeker_profile

        if not profile.hexa_address_filled:
            # Format job seeker address
            profile.update_hexa_address()

        self.job_application.job_seeker.last_checked_at = timezone.now()
        self.job_application.job_seeker.save(update_fields=["last_checked_at"])

        self.clean()
        # There could be a delay between the moment the object is created
        # and the moment it is completed to be sent to the ASP.
        # In the meantime the ASP ID or the SIRET *can change* (mainly because of weekly ASP import scripts).
        # To prevent some ASP processing errors, we do a refresh on some mutable fields.
        self._fill_denormalized_fields()

    @xwf_models.transition()
    def wait_for_asp_response(self, *, file, line_number, archive):
        """
        An employee record is sent to ASP via a JSON file,
        The file name is stored for further feedback processing (also done via a file)
        """
        self.clean()
        self.set_asp_batch_information(file, line_number, archive)

    @xwf_models.transition()
    def reject(self, *, code, label, archive):
        """
        Update status after an ASP rejection of the employee record
        """
        self.clean()
        self.set_asp_processing_information(code, label, archive)

    @xwf_models.transition()
    def process(self, *, code, label, archive, as_duplicate=False):
        if as_duplicate and code != self.ASP_DUPLICATE_ERROR_CODE:
            raise ValueError(f"Code needs to be {self.ASP_DUPLICATE_ERROR_CODE} and not {code} when {as_duplicate=}")

        self.clean()
        self.processed_at = timezone.now()
        self.processed_as_duplicate = as_duplicate
        self.set_asp_processing_information(
            code, label if not as_duplicate else "Statut forcé suite à doublon ASP", archive
        )

    @xwf_models.transition()
    def enable(self, *, user=None):
        self._fill_denormalized_fields()

    @xworkflows.transition_check(EmployeeRecordTransition.ARCHIVE)
    def check_archive(self):
        # We only archive an employee record when the job seeker's approval is expired and can no longer be prolonged
        return not self.job_application.approval.is_valid() and not self.job_application.approval.can_be_prolonged

    @xwf_models.transition()
    def archive(self, *, user=None):
        # Remove proof of processing after delay
        self.archived_json = None

    @xworkflows.transition_check(EmployeeRecordTransition.UNARCHIVE_NEW)
    def check_unarchive_new(self):
        return self.status_based_on_asp_processing_code is Status.NEW

    @xworkflows.transition_check(EmployeeRecordTransition.UNARCHIVE_PROCESSED)
    def check_unarchive_processed(self):
        return self.status_based_on_asp_processing_code is Status.PROCESSED

    @xworkflows.transition_check(EmployeeRecordTransition.UNARCHIVE_REJECTED)
    def check_unarchive_rejected(self):
        return self.status_based_on_asp_processing_code is Status.REJECTED

    def unarchive(self):
        for transition_name in [
            EmployeeRecordTransition.UNARCHIVE_PROCESSED,
            EmployeeRecordTransition.UNARCHIVE_REJECTED,
            EmployeeRecordTransition.UNARCHIVE_NEW,
        ]:
            transition = getattr(self, transition_name)
            if transition.is_available():
                if EmployeeRecord.objects.missed_notifications().filter(pk=self.pk).exists():
                    EmployeeRecordUpdateNotification.objects.update_or_create(
                        employee_record=self,
                        status=NotificationStatus.NEW,
                        defaults={"updated_at": timezone.now},
                    )
                return transition()

        if self.status != Status.ARCHIVED:
            raise xwf_models.InvalidTransitionError()

    def was_sent(self):
        return self.logs.exclude(transition__in=EmployeeRecordTransition.without_asp_exchange()).exists()

    @property
    def status_based_on_asp_processing_code(self):
        if not self.asp_processing_code:
            return Status.NEW
        if self.asp_processing_code in ["0000", self.ASP_DUPLICATE_ERROR_CODE]:
            return Status.PROCESSED
        if self.asp_processing_code[:2] in ["32", "33", "34"]:
            return Status.REJECTED

    @property
    def asp_employer_type(self):
        """
        This is a mapping between itou internal SIAE kinds and ASP ones

        Only needed if profile.is_employed is True

        MUST return None otherwise
        """
        if self.job_application.job_seeker.jobseeker_profile.is_employed:
            return EmployerType.from_itou_siae_kind(self.job_application.to_company.kind)
        return None

    @property
    def asp_prescriber_type(self):
        """
        This is a mapping between itou internal prescriber kinds and ASP ones
        """

        sender_kind = self.job_application.sender_kind

        if sender_kind == SenderKind.JOB_SEEKER:
            # the jobseeker applied directly
            return PrescriberType.SPONTANEOUS_APPLICATION

        if sender_kind == SenderKind.EMPLOYER:
            # SIAE applications also fall into the SPONTANEOUS_APPLICATION type
            return PrescriberType.SPONTANEOUS_APPLICATION

        prescriber_organization = self.job_application.sender_prescriber_organization
        if not prescriber_organization or not prescriber_organization.is_authorized:
            return PrescriberType.PRESCRIBERS

        if prescriber_organization.kind in PrescriberType.names:
            return PrescriberType[prescriber_organization.kind]

        return PrescriberType.OTHER_AUTHORIZED_PRESCRIBERS

    @property
    def asp_siae_type(self):
        """
        Mapping between ASP and itou models for SIAE kind ("Mesure")
        """
        return SiaeMeasure.from_siae_kind(self.job_application.to_company.kind)

    def has_siret_different_from_asp_source(self):
        siret_from_asp_source = (
            self.siret_from_asp_source
            if hasattr(self, "siret_from_asp_source")
            else self.job_application.to_company.siret_from_asp_source()
        )
        return self.siret != siret_from_asp_source

    def has_valid_data_filled(self):
        # In `JobSeekerProfile.clean_model()` some fields are only checked if present, but we need them to be filled
        try:
            has_extra_required_fields = all(
                [
                    self.job_application.job_seeker.jobseeker_profile.birth_country,
                    self.job_application.job_seeker.jobseeker_profile.hexa_commune,  # Any of the hexa fields will do
                ]
            )
        except AttributeError:
            return False
        else:
            if not has_extra_required_fields:
                return False

        # Now we can use the common validation methods
        try:
            self.clean()
        except Exception:
            return False
        return True

    @classmethod
    def from_job_application(cls, job_application, clean=True):
        """
        Alternative and main FS constructor from a JobApplication object

        If an employee record with given criteria (approval, SIAE/ASP structure)
        already exists, this method returns None

        Defensive:
        - raises exception if job application is not suitable for creation of a new employee record
        - job seeker profile must exist before creating an employee record
        """
        assert job_application

        fs = cls(job_application=job_application)

        if clean:
            fs.clean()

        fs._fill_denormalized_fields()

        try:
            fs.validate_unique()
            fs.validate_constraints()
        except ValidationError:
            raise ValidationError(EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE)

        return fs


class EmployeeRecordTransitionLog(xwf_models.BaseTransitionLog, ASPExchangeInformation):
    MODIFIED_OBJECT_FIELD = "employee_record"
    EXTRA_LOG_ATTRIBUTES = (
        ("user", "user", None),
        ("asp_batch_file", "file", None),
        ("asp_batch_line_number", "line_number", None),
        ("asp_processing_code", "code", None),
        ("asp_processing_label", "label", None),
        ("archived_json", "archive", None),
    )

    employee_record = models.ForeignKey(EmployeeRecord, related_name="logs", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="+",
    )
    recovered = models.BooleanField(
        verbose_name="récupéré rétroactivement avec un script",
        default=False,
        editable=False,
    )

    class Meta(ASPExchangeInformation.Meta):
        verbose_name = "log des transitions de la fiche salarié"
        verbose_name_plural = "log des transitions des fiches salarié"
        ordering = ["-timestamp"]


class EmployeeRecordBatch:
    """
    Transient wrapper for a list of employee records.

    Some business validation rules from ASP:
    - no more than 700 employee records per upload
    - serialized JSON file must be 2Mb at most

    This model used by JSON serializer as an header for ASP transmission
    """

    ERROR_BAD_FEEDBACK_FILENAME = "Mauvais nom de fichier de retour ASP"

    # Max number of employee records per upload batch
    MAX_EMPLOYEE_RECORDS = 700

    # Max size of upload file
    MAX_SIZE_BYTES = 2048 * 1024

    # File name format for upload
    REMOTE_PATH_FORMAT = "RIAE_FS_{}.json"

    # Feedback file names end with this string
    FEEDBACK_FILE_SUFFIX = "_FichierRetour"

    def __init__(self, elements):
        if elements and len(elements) > self.MAX_EMPLOYEE_RECORDS:
            raise ValidationError(f"An upload batch can have no more than {self.MAX_EMPLOYEE_RECORDS} elements")

        # id and message fields must be null for upload
        # they may have a value after download
        self.id = None
        self.message = None

        self.elements = elements
        self.upload_filename = self.REMOTE_PATH_FORMAT.format(timezone.now().strftime("%Y%m%d%H%M%S"))

        # add a line number to each FS for JSON serialization
        for idx, er in enumerate(self.elements, start=1):
            er.asp_batch_line_number = idx
            er.asp_processing_code = None
            er.asp_processing_label = None

    def __str__(self):
        return f"FILENAME={self.upload_filename}, NB_RECORDS={len(self.elements)}"

    def __repr__(self):
        # String formating with {field_name=...} forms use __repr__ and not __str__
        return f"{self.upload_filename=}, {len(self.elements)=}"

    @staticmethod
    def feedback_filename(filename):
        """
        Return name of the feedback file
        """
        validate_asp_batch_filename(filename)
        separator = "."
        path, ext = filename.split(separator)
        path += EmployeeRecordBatch.FEEDBACK_FILE_SUFFIX

        return separator.join([path, ext])

    @staticmethod
    def batch_filename_from_feedback(filename):
        """
        Return name of original filename from feedback filename
        """
        separator = "."
        path, ext = filename.split(separator)

        if not path.endswith(EmployeeRecordBatch.FEEDBACK_FILE_SUFFIX):
            raise ValidationError(EmployeeRecordBatch.ERROR_BAD_FEEDBACK_FILENAME)

        # .removesuffix is Python 3.9
        return separator.join([path.removesuffix(EmployeeRecordBatch.FEEDBACK_FILE_SUFFIX), ext])


class EmployeeRecordUpdateNotificationWorkflow(xwf_models.Workflow):
    states = NotificationStatus.choices
    initial_state = Status.NEW

    transitions = (
        (EmployeeRecordTransition.WAIT_FOR_ASP_RESPONSE, NotificationStatus.NEW, NotificationStatus.SENT),
        (EmployeeRecordTransition.REJECT, NotificationStatus.SENT, NotificationStatus.REJECTED),
        (EmployeeRecordTransition.PROCESS, NotificationStatus.SENT, NotificationStatus.PROCESSED),
    )


class EmployeeRecordUpdateNotificationQuerySet(QuerySet):
    def find_by_batch(self, filename, line_number):
        return self.filter(asp_batch_file=filename, asp_batch_line_number=line_number)

    def full_fetch(self):
        return self.select_related(
            "employee_record",
            "employee_record__job_application",
            "employee_record__job_application__approval",
            "employee_record__job_application__to_company",
            "employee_record__job_application__job_seeker",
            "employee_record__job_application__job_seeker__jobseeker_profile__birth_country",
            "employee_record__job_application__job_seeker__jobseeker_profile__birth_place",
            "employee_record__job_application__job_seeker__jobseeker_profile",
            "employee_record__job_application__job_seeker__jobseeker_profile__hexa_commune",
            "employee_record__job_application__sender_prescriber_organization",
        )


class EmployeeRecordUpdateNotification(ASPExchangeInformation, xwf_models.WorkflowEnabled):
    """
    Notification of employee record updates.

    Monitoring of approvals is done via a Postgres trigger (defined in `Approval` app migrations),
    at the moment, only the start and end dates are tracked.
    """

    ASP_MOVEMENT_TYPE = MovementType.UPDATE

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    status = xwf_models.StateField(EmployeeRecordUpdateNotificationWorkflow, verbose_name="statut", max_length=10)

    employee_record = models.ForeignKey(
        EmployeeRecord,
        related_name="update_notifications",
        verbose_name="fiche salarié",
        on_delete=models.CASCADE,
    )

    objects = EmployeeRecordUpdateNotificationQuerySet.as_manager()

    class Meta(ASPExchangeInformation.Meta):
        verbose_name = "notification de changement de la fiche salarié"
        verbose_name_plural = "notifications de changement de la fiche salarié"
        constraints = ASPExchangeInformation.Meta.constraints + [
            # Only allow 1 NEW notification, this is used by the trigger's INSERT ON CONFLICT
            models.UniqueConstraint(
                fields=["employee_record"],
                name="unique_new_employee_record",
                condition=Q(status=NotificationStatus.NEW),
            )
        ]

    def __repr__(self):
        return f"<{type(self).__name__} pk={self.pk}>"

    @xwf_models.transition()
    def wait_for_asp_response(self, *, file, line_number, archive):
        self.set_asp_batch_information(file, line_number, archive)

    @xwf_models.transition()
    def reject(self, *, code, label, archive):
        self.set_asp_processing_information(code, label, archive)

    @xwf_models.transition()
    def process(self, *, code, label, archive):
        self.set_asp_processing_information(code, label, archive)
