import contextlib
import json

import django.db.utils
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Exists, OuterRef
from django.db.models.manager import Manager
from django.db.models.query import F, Q, QuerySet
from django.utils import timezone
from rest_framework.authtoken.admin import User

from itou.approvals.models import Approval
from itou.asp.models import EmployerType, PrescriberType, SiaeKind
from itou.job_applications.enums import SenderKind
from itou.siaes.models import Siae, SiaeFinancialAnnex
from itou.users.models import JobSeekerProfile
from itou.utils.validators import validate_siret

from .enums import MovementType, NotificationStatus, Status
from .exceptions import CloningError, DuplicateCloningError, InvalidStatusError


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

    def _set_archived_json(self, archive):
        if archive is not None:
            with contextlib.suppress(json.JSONDecodeError):
                archive = json.loads(archive)
        self.archived_json = archive

    def set_asp_batch_information(self, file, line_number, archive):
        self.asp_batch_file = file
        self.asp_batch_line_number = line_number
        self._set_archived_json(archive)

    def set_asp_processing_information(self, code, label, archive):
        self.asp_processing_code = code
        self.asp_processing_label = label
        self._set_archived_json(archive)


class EmployeeRecordQuerySet(models.QuerySet):
    def full_fetch(self):
        return self.select_related(
            "financial_annex",
            "job_application",
            "job_application__approval",
            "job_application__to_siae",
            "job_application__job_seeker",
            "job_application__job_seeker__jobseeker_profile__birth_country",
            "job_application__job_seeker__jobseeker_profile__birth_place",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__job_seeker__jobseeker_profile__hexa_commune",
            "job_application__sender_prescriber_organization",
        )

    # Search queries
    def for_siae(self, siae):
        return self.filter(
            job_application__to_siae=siae,
            asp_id=F("job_application__to_siae__convention__asp_id"),
        )

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
                created_at__lt=timezone.now() - relativedelta(months=6),  # Keep them at least 6 months
            )
        )

    def asp_duplicates(self):
        """
        Return REJECTED employee records with error code '3436'.
        These employee records are considered as duplicates by ASP.
        """
        return self.filter(status=Status.REJECTED).filter(asp_processing_code=EmployeeRecord.ASP_DUPLICATE_ERROR_CODE)

    def orphans(self):
        """
        Employee records with an `asp_id` different from their hiring SIAE.
        Could occur when using `siae.move_siae_data` management command.
        """
        return self.exclude(job_application__to_siae__convention__asp_id=F("asp_id"))


class EmployeeRecord(ASPExchangeInformation):
    """
    EmployeeRecord - Fiche salarié (FS for short)

    Holds information needed for JSON exports and processing by ASP
    """

    ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED = "La candidature doit être acceptée"
    ERROR_JOB_APPLICATION_WITHOUT_APPROVAL = "L'embauche n'est pas reliée à un PASS IAE"

    ERROR_EMPLOYEE_RECORD_IS_DUPLICATE = "Une fiche salarié pour ce PASS IAE et cette SIAE existe déjà"
    ERROR_EMPLOYEE_RECORD_INVALID_STATE = "La fiche salarié n'est pas dans l'état requis pour cette action"

    ERROR_NO_CONVENTION_AVAILABLE = "La structure actuelle ne dispose d'aucune convention"

    CAN_BE_DISABLED_STATES = [Status.NEW, Status.REJECTED, Status.PROCESSED]

    ASP_MOVEMENT_TYPE = MovementType.CREATION

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    processed_at = models.DateTimeField(verbose_name="date d'intégration", null=True)
    status = models.CharField(max_length=10, verbose_name="statut", choices=Status.choices, default=Status.NEW)

    # Job application has references on many mandatory parts of the E.R.:
    # - SIAE / asp id
    # - Employee
    # - Approval
    job_application = models.ForeignKey(
        "job_applications.jobapplication",
        on_delete=models.SET_NULL,
        null=True,
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
    asp_id = models.PositiveIntegerField(verbose_name="identifiant ASP de la SIAE")

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
                fields=["asp_id", "approval_number"],
                name="unique_asp_id_approval_number",
            )
        ]

    def __str__(self):
        return (
            f"PK:{self.pk} PASS:{self.approval_number} SIRET:{self.siret} JA:{self.job_application} "
            f"JOBSEEKER:{self.job_seeker} STATUS:{self.status} ASP_ID:{self.asp_id}"
        )

    def _clean_job_application(self):
        """
        Check if job application is valid for FS
        """
        if not self.job_application.to_siae.convention:
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
        self.siret = self.siret_from_asp_source(self.job_application.to_siae)
        self.asp_id = self.job_application.to_siae.convention.asp_id
        self.approval_number = self.job_application.approval.number

    # Business methods

    def update_as_ready(self):
        """
        Prepare the employee record for transmission

        Status: NEW | REJECTED | DISABLED => READY
        """
        if self.status not in [Status.NEW, Status.REJECTED, Status.DISABLED]:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        profile = self.job_seeker.jobseeker_profile

        if not profile.hexa_address_filled:
            # Format job seeker address
            profile.update_hexa_address()

        self.job_seeker.last_checked_at = timezone.now()
        self.job_seeker.save(update_fields=["last_checked_at"])

        self.clean()
        # There could be a delay between the moment the object is created
        # and the moment it is completed to be sent to the ASP.
        # In the meantime the ASP ID or the SIRET *can change* (mainly because of weekly ASP import scripts).
        # To prevent some ASP processing errors, we do a refresh on some mutable fields.
        self._fill_denormalized_fields()

        # If we reach this point, the employee record is ready to be serialized
        # and can be sent to ASP
        self.status = Status.READY
        self.save()

    def update_as_sent(self, asp_filename, line_number, archive):
        """
        An employee record is sent to ASP via a JSON file,
        The file name is stored for further feedback processing (also done via a file)

        Status: READY => SENT
        """
        if not self.status == Status.READY:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()
        self.status = Status.SENT
        self.set_asp_batch_information(asp_filename, line_number, archive)

        self.save()

    def update_as_rejected(self, code, label, archive):
        """
        Update status after an ASP rejection of the employee record

        Status: SENT => REJECTED
        """
        if not self.status == Status.SENT:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()
        self.status = Status.REJECTED
        self.set_asp_processing_information(code, label, archive)

        self.save()

    def update_as_processed(self, code, label, archive):
        if not self.status == Status.SENT:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()
        self.status = Status.PROCESSED
        self.processed_at = timezone.now()
        self.set_asp_processing_information(code, label, archive)

        self.save()

    def update_as_disabled(self):
        if not self.can_be_disabled:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.status = Status.DISABLED
        self.save()

    def update_as_new(self):
        if self.status != Status.DISABLED:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self._fill_denormalized_fields()

        self.status = Status.NEW
        self.save()

    def update_as_archived(self):
        # We only archive an employee record when the job seeker's approval is expired and can no longer be prolonged
        if self.job_application.approval.is_valid() or self.job_application.approval.can_be_prolonged:
            raise InvalidStatusError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        # Remove proof of processing after delay
        self.status = Status.ARCHIVED
        self.archived_json = None

        with transaction.atomic():  # In case we failed the "unique_asp_id_approval_number" constraint
            self.save()

    def update_as_processed_as_duplicate(self, archive):
        """
        Force status to `PROCESSED` if the employee record has been marked
        as duplicate by ASP (error code 3436).

        Can only be done when employee record is:
            - in `REJECTED` state,
            - with a `3436` error code.
        """
        if self.status != Status.REJECTED or self.asp_processing_code != self.ASP_DUPLICATE_ERROR_CODE:
            raise InvalidStatusError(
                f"{self.ERROR_EMPLOYEE_RECORD_INVALID_STATE} ({self.status}, {self.asp_processing_code})"
            )

        self.clean()
        self.status = Status.PROCESSED
        self.processed_at = timezone.now()
        self.processed_as_duplicate = True
        self.set_asp_processing_information(self.ASP_DUPLICATE_ERROR_CODE, "Statut forcé suite à doublon ASP", archive)

        self.save()

    def clone(self):
        """
        Create and return a NEW copy of an employee record, this is useful when orphans are detected.
        If cloning is successful, current employee record is DISABLED (if possible) to avoid conflicts.

        Raises `CloningError` if cloning conditions are not met.
        """
        if not self.pk:
            raise CloningError("This employee record has not been saved yet (no PK).")

        if not self.job_application.to_siae.convention:
            raise CloningError(f"SIAE {self.job_application.to_siae.siret} has no convention")

        # Cleanup clone fields
        er_copy = EmployeeRecord(
            status=Status.NEW,
            job_application=self.job_application,
            approval_number=self.approval_number,
            asp_id=self.job_application.to_siae.convention.asp_id,
            siret=EmployeeRecord.siret_from_asp_source(self.job_application.to_siae),
            asp_processing_label=f"Fiche salarié clonée (pk origine: {self.pk})",
        )

        try:
            with transaction.atomic():
                er_copy.save()
        except django.db.utils.IntegrityError as ex:
            raise DuplicateCloningError(
                f"The clone is a duplicate of ({er_copy.asp_id=}, {er_copy.approval_number=})"
            ) from ex

        # Disable current object to avoid conflicts
        if self.can_be_disabled:
            self.update_as_disabled()

        return er_copy

    @property
    def can_be_disabled(self):
        return self.status in self.CAN_BE_DISABLED_STATES

    @property
    def job_seeker(self) -> User:
        """
        Shortcut to job application user / job seeker
        """
        return self.job_application.job_seeker if self.job_application else None

    @property
    def job_seeker_profile(self) -> JobSeekerProfile | None:
        """
        Shortcut to job seeker profile
        """
        if self.job_application and hasattr(self.job_application.job_seeker, "jobseeker_profile"):
            return self.job_application.job_seeker.jobseeker_profile

        return None

    @property
    def approval(self) -> Approval | None:
        """
        Shortcut to job application approval
        """
        return self.job_application.approval if self.job_application and self.job_application.approval else None

    @property
    def financial_annex_number(self):
        """
        Shortcut to financial annex number (can be null in early stages of life cycle)
        """
        return self.financial_annex.number if self.financial_annex else None

    @property
    def asp_convention_id(self):
        """
        ASP convention ID (from siae.convention.asp_convention_id)
        """
        if self.job_application and self.job_application.to_siae:
            return self.job_application.to_siae.convention.asp_convention_id

        return None

    @property
    def asp_employer_type(self):
        """
        This is a mapping between itou internal SIAE kinds and ASP ones

        Only needed if profile.is_employed is True

        MUST return None otherwise
        """
        if self.job_seeker_profile and self.job_seeker_profile.is_employed:
            return EmployerType.from_itou_siae_kind(self.job_application.to_siae.kind)
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

        if sender_kind == SenderKind.SIAE_STAFF:
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
        return SiaeKind.from_siae_kind(self.job_application.to_siae.kind)

    @property
    def is_orphan(self):
        """Orphan employee records have different stored and actual `asp_id` fields."""
        return self.job_application.to_siae.convention.asp_id != self.asp_id

    @staticmethod
    def siret_from_asp_source(siae):
        """
        Fetch SIRET number of ASP source structure ("mother" SIAE)
        """
        if siae.source != Siae.SOURCE_ASP:
            main_siae = Siae.objects.get(convention=siae.convention, source=Siae.SOURCE_ASP)
            return main_siae.siret

        return siae.siret

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

        # Mandatory check, must be done only once
        if EmployeeRecord.objects.filter(
            asp_id=job_application.to_siae.convention.asp_id,
            approval_number=job_application.approval.number,
        ).exists():
            raise ValidationError(EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE)

        fs.asp_id = job_application.to_siae.convention.asp_id
        fs.approval_number = job_application.approval.number

        # Fetch correct number if SIAE is an antenna
        fs.siret = EmployeeRecord.siret_from_asp_source(job_application.to_siae)

        return fs


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


class EmployeeRecordUpdateNotificationQuerySet(QuerySet):
    def find_by_batch(self, filename, line_number):
        return self.filter(asp_batch_file=filename, asp_batch_line_number=line_number)


class EmployeeRecordUpdateNotification(ASPExchangeInformation):
    """
    Notification of PROCESSED employee record updates.

    Monitoring of approvals is done via a Postgres trigger (defined in `Approval` app migrations),
    at the moment, only the start and end dates are tracked.
    """

    ASP_MOVEMENT_TYPE = MovementType.UPDATE

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    status = models.CharField(
        verbose_name="statut",
        max_length=10,
        choices=NotificationStatus.choices,
        default=NotificationStatus.NEW,
    )

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

    def update_as_sent(self, filename, line_number, archive):
        if self.status not in [NotificationStatus.NEW, NotificationStatus.REJECTED]:
            raise ValidationError(f"Invalid status to update as SENT (currently: {self.status})")

        self.status = NotificationStatus.SENT
        self.set_asp_batch_information(filename, line_number, archive)

        self.save()

    def update_as_rejected(self, code, label, archive):
        if not self.status == Status.SENT:
            raise ValidationError(f"Invalid status to update as REJECTED (currently: {self.status})")

        self.status = Status.REJECTED
        self.set_asp_processing_information(code, label, archive)

        self.save()

    def update_as_processed(self, code, label, archive):
        if not self.status == Status.SENT:
            raise ValidationError(f"Invalid status to update as PROCESSED (currently: {self.status})")

        self.status = Status.PROCESSED
        self.set_asp_processing_information(code, label, archive)

        self.save()
