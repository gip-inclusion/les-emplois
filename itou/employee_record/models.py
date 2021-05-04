from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from itou.asp.models import EmployerType, PrescriberType, SiaeKind
from itou.job_applications.models import JobApplication
from itou.siaes.models import SiaeFinancialAnnex


# Validators


def validate_asp_batch_filename(value):
    """
    Simple validation of batch file name
    (ASP backend is picky about it)
    """
    if value and value.startswith("RIAE_FS_") and value.endswith(".json") and len(value) == 27:
        return
    raise ValidationError(f"Le format du nom de fichier ASP est incorrect: {value}")


class EmployeeRecordQuerySet(models.QuerySet):
    def ready(self):
        """
        These FS are ready to to be sent to ASP
        """
        return self.filter(status=EmployeeRecord.Status.READY)

    def sent(self):
        return self.filter(status=EmployeeRecord.Status.SENT)

    def sent_for_siae(self, siae):
        return self.sent().filter(job_application__to_siae=siae).select_related("job_application")

    def rejected(self):
        return self.filter(status=EmployeeRecord.Status.REJECTED)

    def rejected_for_siae(self, siae):
        return self.rejected().filter(job_application__to_siae=siae).select_related("job_application")

    def processed(self):
        return self.filter(status=EmployeeRecord.Status.PROCESSED)

    def processed_for_siae(self, siae):
        return self.processed().filter(job_application__to_siae=siae).select_related("job_application")

    def archived(self):
        """
        Archived employee records (completed and having a JSON archive)
        """
        return self.filter(status=EmployeeRecord.Status.ARCHIVED)

    def find_by_batch(self, filename, line_number):
        """
        Fetch a single employee record with ASP batch file input parameters
        """
        return self.filter(asp_batch_file=filename, asp_batch_line_number=line_number)


class EmployeeRecord(models.Model):
    """
    EmployeeRecord - Fiche salarié (FS for short)

    Holds information needed for JSON exports and processing by ASP
    """

    ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED = "La candidature doit être acceptée"
    ERROR_JOB_APPLICATION_TOO_RECENT = "L'embauche a été validé trop récemment"
    ERROR_JOB_SEEKER_TITLE = "La civilité du salarié est obligatoire"
    ERROR_JOB_SEEKER_BIRTH_COUNTRY = "Le pays de naissance est obligatoire"
    ERROR_JOB_APPLICATION_WITHOUT_APPROVAL = "L'embauche n'est pas reliée à un PASS IAE"

    ERROR_JOB_SEEKER_TITLE = "La civilité du salarié est obligatoire"
    ERROR_JOB_SEEKER_BIRTH_COUNTRY = "Le pays de naissance est obligatoire"
    ERROR_JOB_SEEKER_HAS_NO_PROFILE = "Cet utilisateur n'a pas de profil de demandeur d'emploi enregistré"

    ERROR_EMPLOYEE_RECORD_IS_DUPLICATE = "Une fiche salarié pour ce PASS IAE et cette SIAE existe déjà"
    ERROR_EMPLOYEE_RECORD_INVALID_STATE = "La fiche salarié n'est pas dans l'état requis pour cette action"

    # 'C' stands for Creation
    ASP_MOVEMENT_TYPE = "C"

    class Status(models.TextChoices):
        """
        Status of the employee record

        Self-explanatory on the meaning, however:
        - an E.R. can be modified until it is in the PROCESSED state
        - after that, the FS is "archived" and can't be used for further interaction
        """

        NEW = "NEW", "Nouvelle fiche salarié"
        READY = "READY", "Données complètes, prêtes à l'envoi ASP"
        SENT = "SENT", "Envoyée ASP"
        REJECTED = "REJECTED", "Rejetée ASP"
        PROCESSED = "PROCESSED", "Traitée ASP"
        ARCHIVED = "ARCHIVED", "Archivée"

    created_at = models.DateTimeField(verbose_name=("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=("Date de modification"), default=timezone.now)
    status = models.CharField(max_length=10, verbose_name="Statut", choices=Status.choices, default=Status.NEW)

    # Job application has references on many mandatory parts of the E.R.:
    # - SIAE / asp id
    # - Employee
    # - Approval
    job_application = models.ForeignKey(
        "job_applications.jobapplication",
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="Candidature / embauche",
    )

    # Employee records must be linked to a valid financial annex
    # This field can't be automatically filled, the user will be asked
    # to select a valid one manually
    financial_annex = models.ForeignKey(
        SiaeFinancialAnnex, verbose_name="Annexe financière", null=True, on_delete=models.SET_NULL
    )

    # These fields are duplicated to act as constraint fields on DB level
    approval_number = models.CharField(max_length=12, verbose_name="Numéro d'agrément")
    asp_id = models.IntegerField(verbose_name="Identifiant ASP de la SIAE")

    # ASP processing part
    asp_processing_code = models.CharField(max_length=4, verbose_name="Code de traitement ASP", null=True)
    asp_processing_label = models.CharField(max_length=100, verbose_name="Libellé de traitement ASP", null=True)

    # Employee records are sent to ASP in a JSON file,
    # We keep track of the name for processing feedback
    # The format of the file name is EXACTLY: RIAE_FS_ AAAAMMJJHHMMSS (27 chars)
    asp_batch_file = models.CharField(
        max_length=27,
        verbose_name="Fichier de batch ASP",
        null=True,
        db_index=True,
        validators=[validate_asp_batch_filename],
    )
    # Line number of the employee record in the batch file
    # Unique pair with `asp_batch_file`
    asp_batch_line_number = models.IntegerField(
        verbose_name="Ligne correspondante dans le fichier batch ASP", null=True, db_index=True
    )

    # Once correctly processed by ASP, the employee record is archived:
    # - it can't be changed anymore
    # - a serialized version of the employee record is stored (as proof, and for API concerns)
    # The API will not use JSON serializers on a regular basis,
    # except for the archive serialization, which occurs once.
    # It will only return a list of this JSON field for archived employee records.
    archived_json = models.JSONField(verbose_name="Archive JSON de la fiche salarié", null=True)

    objects = models.Manager.from_queryset(EmployeeRecordQuerySet)()

    class Meta:
        verbose_name = "Fiche salarié"
        verbose_name_plural = "Fiches salarié"
        constraints = [
            models.UniqueConstraint(fields=["asp_id", "approval_number"], name="unique_asp_id_approval_number")
        ]
        unique_together = ["asp_batch_file", "asp_batch_line_number"]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.asp_id} - {self.approval_number} - {self.job_seeker}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()

        super().save(*args, **kwargs)

    def _clean_job_application(self):
        """
        Check if job application is valid for FS
        """

        if not self.job_application.state.is_accepted:
            raise ValidationError(self.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED)

        if not self.job_application.approval:
            raise ValidationError(self.ERROR_JOB_APPLICATION_WITHOUT_APPROVAL)

        if self.job_application.can_be_cancelled:
            raise ValidationError(self.ERROR_JOB_APPLICATION_TOO_RECENT)

    def _clean_job_seeker(self):
        """
        Check if data provided for the job seeker part of the FS is complete / valid
        """
        job_seeker = self.job_application.job_seeker

        # Check if user is "clean"
        job_seeker.clean()

        if not job_seeker.has_jobseeker_profile:
            raise ValidationError(self.ERROR_JOB_SEEKER_HAS_NO_PROFILE)

        # Further validation in the job seeker profile
        job_seeker.jobseeker_profile.clean()

    def clean(self):
        # see private methods above
        self._clean_job_application()
        self._clean_job_seeker()

    # Business methods

    def update_as_ready(self):
        """
        Prepare the employee record for transmission

        Status: NEW => READY
        """
        if self.status not in [EmployeeRecord.Status.NEW, EmployeeRecord.Status.REJECTED]:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        profile = self.job_seeker.jobseeker_profile

        if not profile.hexa_address_filled:
            # Format job seeker address
            profile.update_hexa_address()

        self.clean()

        # If we reach this point, the employee record is ready to be serialized
        # and can be sent to ASP
        self.status = self.Status.READY
        self.save()

    def update_as_sent(self, asp_filename, line_number):
        """
        An employee record is sent to ASP via a JSON file,
        The file name is stored for further feedback processing (also done via a file)

        Status: READY => SENT
        """
        if not self.status == EmployeeRecord.Status.READY:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()

        self.asp_batch_file = asp_filename
        self.asp_batch_line_number = line_number
        self.status = EmployeeRecord.Status.SENT
        self.save()

    def update_as_rejected(self, code, label):
        """
        Update status after an ASP rejection of the employee record

        Status: SENT => REJECTED
        """
        if not self.status == EmployeeRecord.Status.SENT:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()
        self.status = EmployeeRecord.Status.REJECTED
        self.asp_processing_code = code
        self.asp_processing_label = label
        self.save()

    def update_as_accepted(self, code, label, archive):
        if not self.status == EmployeeRecord.Status.SENT:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        self.clean()
        self.status = EmployeeRecord.Status.PROCESSED
        self.asp_processing_code = code
        self.asp_processing_label = label
        self.archived_json = archive
        self.save()

    @property
    def is_archived(self):
        """
        Once in final state (PROCESSED), an EmployeeRecord is archived.
        See model save() and clean() method.
        """
        return self.status == self.Status.PROCESSED and self.json is not None

    @property
    def is_updatable(self):
        """
        Once in final state (PROCESSED), an EmployeeRecord is not updatable anymore.

        Check this property before using save()

        If an employee record is archived or in SENT status, updating and using save()
        will throw a ValidationError

        An EmployeeRecord object must not be updated when it has been sent to ASP (waiting for validation)
        except via specific business methods

        See model save() and clean() method.
        """
        return self.status != self.Status.SENT and not self.is_archived

    @property
    def job_seeker(self):
        """
        Shortcut to job application user / job seeker
        """
        return self.job_application.job_seeker if self.job_application else None

    @property
    def job_seeker_profile(self):
        """
        Shortcut to job seeker profile
        """
        if self.job_application and hasattr(self.job_application.job_seeker, "jobseeker_profile"):
            return self.job_application.job_seeker.jobseeker_profile

        return None

    @property
    def approval(self):
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

        if sender_kind == JobApplication.SENDER_KIND_JOB_SEEKER:
            # the job seeker applied directly
            return PrescriberType.SPONTANEOUS_APPLICATION
        elif sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
            # an SIAE applied
            return PrescriberType.UNKNOWN

        return PrescriberType.from_itou_prescriber_kind(sender_kind)

    @property
    def asp_siae_type(self):
        """
        Mapping between ASP and itou models for SIAE kind ("Mesure")
        """
        return SiaeKind.from_siae_kind(self.job_application.to_siae.kind)

    @property
    def batch_line_number(self):
        """
        This transient field is updated at runtime for JSON serialization.

        It is the batch line number of the employee record.
        """
        if not hasattr(self, "_batch_line_number"):
            self._batch_line_number = 1

        return self._batch_line_number

    @classmethod
    def from_job_application(cls, job_application):
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

        fs.clean()

        # Mandatory check, must be done only once
        if EmployeeRecord.objects.filter(
            asp_id=job_application.to_siae.convention.asp_id,
            approval_number=job_application.approval.number,
        ).exists():
            raise ValidationError(EmployeeRecord.ERROR_EMPLOYEE_RECORD_IS_DUPLICATE)

        fs.asp_id = job_application.to_siae.convention.asp_id
        fs.approval_number = job_application.approval.number

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

    def __init__(self, employee_records):
        if employee_records and len(employee_records) > self.MAX_EMPLOYEE_RECORDS:
            raise ValidationError(
                f"An upload batch can have no more than {self.MAX_EMPLOYEE_RECORDS} employee records"
            )

        # id and message fields must be null for upload
        # they may have a value after download
        self.id = None
        self.message = None

        self.employee_records = employee_records
        self.upload_filename = self.REMOTE_PATH_FORMAT.format(timezone.now().strftime("%Y%m%d%H%M%S"))

        # add a line number to each FS for JSON serialization
        for idx, er in enumerate(self.employee_records):
            er.batch_line = idx

    def __str__(self):
        return f"{self.upload_filename}"

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
