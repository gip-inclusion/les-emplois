from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from itou.asp.models import EmployerType, PrescriberType, SiaeKind
from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae, SiaeFinancialAnnex
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


# Oddly enough, no month param for timedeltas
# => approximate 1 month to 30 days (see base settings)
ARCHIVING_DELTA = timezone.timedelta(days=settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS)


class EmployeeRecordQuerySet(models.QuerySet):
    """
    Queryset functions for EmployeeRecord model
    """

    def full_fetch(self):
        """
        Also fetch main employee record related objects:
        - financial annex
        - job application
        - job seeker
        - job seeker profile
        """
        return self.select_related(
            "financial_annex",
            "job_application",
            "job_application__approval",
            "job_application__to_siae",
            "job_application__job_seeker",
            "job_application__job_seeker__birth_country",
            "job_application__job_seeker__birth_place",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__job_seeker__jobseeker_profile__hexa_commune",
        )

    # Status filters

    def ready(self):
        """
        These FS are ready to to be sent to ASP
        """
        return self.filter(status=EmployeeRecord.Status.READY)

    def ready_for_siae(self, siae):
        return self.ready().filter(job_application__to_siae=siae).select_related("job_application")

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

    # Search queries

    def find_by_batch(self, filename, line_number):
        """
        Fetch a single employee record with ASP batch file input parameters
        """
        return self.filter(asp_batch_file=filename, asp_batch_line_number=line_number)

    def archivable(self):
        """
        Fetch employee records in PROCESSED state for more than EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS
        """
        return self.processed().filter(processed_at__lte=timezone.now() - ARCHIVING_DELTA)


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

    ERROR_NO_CONVENTION_AVAILABLE = "La structure actuelle ne dispose d'aucune convention"

    # 'C' stands for Creation
    ASP_MOVEMENT_TYPE = "C"

    class Status(models.TextChoices):
        """
        Status of the employee record

        Self-explanatory on the meaning, however:
        - an E.R. can be modified until it is in the PROCESSED state
        - after that, the FS is "archived" and can't be used for further interaction
        """

        NEW = "NEW", "Nouvelle"
        READY = "READY", "Complétée"
        SENT = "SENT", "Envoyée"
        REJECTED = "REJECTED", "En erreur"
        PROCESSED = "PROCESSED", "Intégrée"
        ARCHIVED = "ARCHIVED", "Archivée"

    created_at = models.DateTimeField(verbose_name=("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=("Date de modification"), default=timezone.now)
    processed_at = models.DateTimeField(verbose_name=("Date d'intégration"), null=True)
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
        related_name="employee_record",
    )

    # Employee records may be linked to a valid financial annex
    # This field can't be automatically filled, the user will be asked
    # to select a valid one manually
    financial_annex = models.ForeignKey(
        SiaeFinancialAnnex, verbose_name="Annexe financière", null=True, on_delete=models.SET_NULL
    )

    # These fields are duplicated to act as constraint fields on DB level
    approval_number = models.CharField(max_length=12, verbose_name="Numéro d'agrément")
    asp_id = models.IntegerField(verbose_name="Identifiant ASP de la SIAE")

    # If the SIAE is an "antenna",
    # we MUST provide the SIRET of the SIAE linked to the financial annex on ASP side (i.e. "parent/mother" SIAE)
    # NOT the actual SIAE (which can be fake and unrecognized by ASP).
    siret = models.CharField(
        verbose_name="Siret structure mère", max_length=14, validators=[validate_siret], db_index=True
    )

    # ASP processing part
    asp_processing_code = models.CharField(max_length=4, verbose_name="Code de traitement ASP", null=True)
    asp_processing_label = models.CharField(max_length=200, verbose_name="Libellé de traitement ASP", null=True)

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
        return f"PK:{self.pk} PASS:{self.approval_number} SIRET:{self.siret} JOBSEEKER:{self.job_seeker}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()

        super().save(*args, **kwargs)

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
        # Note that the job seeker profile validation is done
        # via `clean_model` and not `clean` : see comments on `JobSeekerProfile.clean_model`
        job_seeker.jobseeker_profile.clean_model()

    def clean(self):
        # see private methods above
        self._clean_job_application()
        self._clean_job_seeker()

    # Business methods

    def update_as_ready(self):
        """
        Prepare the employee record for transmission

        Status: NEW | REJECTED => READY
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

        # There could be a delay between the moment the object
        # is created and the moment it is sent to ASP.
        # In the meantime asp_id / SIRET *can change*
        # (mainly because of weekly ASP import scripts).
        # To prevent some ASP processing errors, we do a refresh
        # on some mutable fields before sending:
        # - ASP ID
        # - SIRET number
        self.siret = EmployeeRecord.siret_from_asp_source(self.job_application.to_siae)
        self.asp_id = self.job_application.to_siae.convention.asp_id

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
        self.processed_at = timezone.now()
        self.asp_processing_code = code
        self.asp_processing_label = label
        self.archived_json = archive
        self.save()

    def update_as_archived(self, save=True):
        """
        Can only archive employee record if already PROCESSED
        `save` parameter is for bulk updates in management command
        """
        if self.status != EmployeeRecord.Status.PROCESSED:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        # Check that we are past archiving delay before ... archiving
        if self.processed_at >= timezone.now() - ARCHIVING_DELTA:
            raise ValidationError(self.ERROR_EMPLOYEE_RECORD_INVALID_STATE)

        # Remove proof of processing after delay
        self.status = EmployeeRecord.Status.ARCHIVED
        self.archived_json = None

        if save:
            self.save()
        else:
            # Override .save() update of `updated_at` when using bulk updates
            self.updated_at = timezone.now()

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
        return self.status not in [self.Status.SENT, self.Status.READY] and not self.is_archived

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

    # FIXME:
    # This property is currently *never* accepted in production
    # This has to be fixed with ASP (or not)
    # In the meantime the serializer will use a fixed value for this field
    # (see `tmp_prescriber_type` property)
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
            # Notify ASP : UNKNOWN code does not work for SIAE
            # FIXME return PrescriberType.UNKNOWN
            return PrescriberType.SPONTANEOUS_APPLICATION

        prescriber_organization = self.job_application.sender_prescriber_organization

        # This workaround is under investigation (systematically fails if UNKNOW is chosen)
        return (
            PrescriberType.from_itou_prescriber_kind(prescriber_organization.kind).value
            if prescriber_organization
            else PrescriberType.AUTHORIZED_PRESCRIBERS
        )

    @property
    def tmp_asp_prescriber_type(self):
        # this is temporary (read above)
        return PrescriberType.SPONTANEOUS_APPLICATION

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
        for idx, er in enumerate(self.employee_records, start=1):
            er.asp_batch_line_number = idx
            er.asp_processing_code = None
            er.asp_processing_label = None

    def __str__(self):
        return f"FIL£NAME:{self.upload_filename} NB_RECORDS:{len(self.employee_records)}"

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
