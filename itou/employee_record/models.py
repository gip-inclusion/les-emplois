from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.asp.models import EmployerType, PrescriberType, SiaeType
from itou.job_applications.models import JobApplication


class Status(models.TextChoices):
    """
    Status of the employee record

    Self-explanatory on the meaning, however:
    - an E.R. can be modified until it is in the PROCESSED state
    - after that, the FS is "archived" and can't be used for further interaction
    """

    NEW = "NEW", _("Nouvelle fiche salarié")
    READY = "READY", _("Données complètes, prêtes à l'envoi ASP")
    SENT = "SENT", _("Envoyée ASP")
    REJECTED = "REJECTED", _("Rejet ASP")
    PROCESSED = "PROCESSED", _("Traitée ASP")
    ARCHIVED = "ARCHIVED", _("Archivée")


class EmployeeRecordQuerySet(models.QuerySet):
    def ready(self):
        """
        These FS are ready to to be sent to ASP
        """
        return self.filter(status=Status.READY)

    def sent(self):
        return self.filter(status=Status.SENT)

    def rejected(self):
        return self.filter(status=Status.REJECTED)

    def processed(self):
        return self.filter(status=Status.PROCESSED)

    def archived(self):
        """
        Archived employee records (completed and having a JSON archive)
        """
        return self.filter(status=Status.ARCHIVED)


class EmployeeRecord(models.Model):
    """
    EmployeeRecord - Fiche salarié (FS for short)

    Holds information needed for JSON exports and processing by ASP
    """

    ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED = _("La candidature doit être acceptée")
    ERROR_JOB_APPLICATION_TOO_RECENT = _("L'embauche a été validé trop récemment")
    ERROR_JOB_SEEKER_TITLE = _("La civilité du salarié est obligatoire")
    ERROR_JOB_SEEKER_BIRTH_COUNTRY = _("Le pays de naissance est obligatoire")

    ERROR_JOB_SEEKER_HAS_NO_PROFILE = "Cet utilisateur n'a pas de profil de demandeur d'emploi enregistré"

    ASP_MOVEMENT_TYPE = "C"

    created_at = models.DateTimeField(verbose_name=("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=("Date de modification"), default=timezone.now)
    status = models.CharField(max_length=10, verbose_name=_("Statut"), choices=Status.choices, default=Status.NEW)

    # Itou part

    # Job application has references on many mandatory parts of the E.R.:
    # - SIAE / asp id
    # - Employee
    # - Approval
    job_application = models.ForeignKey(
        "job_applications.jobapplication",
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Candidature / embauche"),
    )

    # These fields are duplicated to act as constraint fields on DB level
    approval_number = models.CharField(max_length=12, verbose_name=_("Numéro d'agrément"))
    asp_id = models.IntegerField(verbose_name=_("ID ASP de la SIAE"))

    # ASP processing part
    asp_processing_code = models.CharField(max_length=4, verbose_name=_("Code de traitement ASP"), blank=True)
    asp_processing_label = models.CharField(max_length=100, verbose_name=_("Libellé de traitement ASP"), blank=True)
    asp_process_response = models.JSONField(verbose_name=_("Réponse du traitement ASP"), null=True)

    # Once correctly processed by ASP, the employee record is archived:
    # - it can't be changed anymore
    # - a serialized version of the employee record is stored (as proof, and for API concerns)
    # The API will not use JSON serializers on a regular basis,
    # except for the archive serialization, which occurs once.
    # It will only return a list of this JSON field for archived employee records.
    archived_json = models.JSONField(verbose_name=_("Fiche salarié au format JSON (archive)"), null=True)
    objects = models.Manager.from_queryset(EmployeeRecordQuerySet)()

    class Meta:
        verbose_name = _("Fiche salarié")
        verbose_name_plural = _("Fiches salarié")
        constraints = [
            models.UniqueConstraint(fields=["asp_id", "approval_number"], name="unique_asp_id_approval_number")
        ]
        ordering = ["-created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.batch_line_line = 1

    def __str__(self):
        return f"{self.asp_id} - {self.approval_number} - {self.job_seeker}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()

        # FIXME: crap
        if self.job_seeker_profile:
            self.job_seeker_profile.save()

        super().save(*args, **kwargs)

    def _clean_job_application(self):
        """
        Check if job application is valid for FS
        """
        ja = self.job_application

        if not ja.is_state_accepted:
            raise ValidationError(self.ERROR_JOB_APPLICATION_MUST_BE_ACCEPTED)

        if ja.can_be_cancelled:
            raise ValidationError(self.ERROR_JOB_APPLICATION_TOO_RECENT)

    def _clean_job_seeker(self):
        """
        Check if data provided for the job seeker part of the FS is complete / valid
        """
        job_seeker = self.job_application.job_seeker
        job_seeker.clean()

        if not job_seeker.has_jobseeker_profile:
            raise ValidationError(self.ERROR_JOB_SEEKER_HAS_NO_PROFILE)

        # Validation takes place in the job seeker profile
        job_seeker.jobseeker_profile.clean()

    def clean(self):
        # see private methods above
        self._clean_job_application()
        self._clean_job_seeker()

    # Business methods

    def prepare(self):
        """
        Prepare the employee record for transmission

        This method can raise ValidationError
        """
        profile = self.job_seeker.jobseeker_profile

        if not profile.hexa_address_filled:
            # Format job seeker address
            profile.update_hexa_address()

        self.job_seeker.clean()
        profile.clean()

        # If we reach this point, the employee record is ready to be serialized
        # and can be sent to ASP
        self.status = Status.READY
        self.save()

    @property
    def is_archived(self):
        """
        Once in final state (PROCESSED), an EmployeeRecord is archived.
        See model save() and clean() method.
        """
        return self.status == Status.PROCESSED and self.json is not None

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
        return self.status != Status.SENT and not self.is_archived

    @property
    def job_seeker(self):
        """
        Shortcut to job application user / job seeker
        """
        if self.job_application:
            return self.job_application.job_seeker

        return None

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
        if self.job_application and self.job_application.approval:
            return self.job_application.approval

        return None

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
        """
        return EmployerType.from_itou_siae_kind(self.job_application.to_siae.kind)

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

        return PrescriberType.from_itou_prescriber_kind(self.job_application.sender_kind)

    @property
    def asp_siae_type(self):
        """
        Mapping between ASP and itou models for SIAE kind ("Mesure")
        """
        return SiaeType.from_siae_kind(self.job_application.to_siae.kind)

    @property
    def movement_type(self):
        """
        This field is constant and needed for JSON serialization

        It means 'C'reation
        """
        return self._ASP_MOVEMENT_TYPE

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

        If an employee record with given criterias (approval, SIAE/ASP structure)
        already exists, this method returns None
        """
        assert job_application

        if (
            job_application.can_be_cancelled
            or not job_application.state.is_accepted
            or not job_application.approval
            or cls.objects.filter(
                asp_id=job_application.to_siae.convention.asp_id,
                approval_number=job_application.approval.number,
            ).exists()
        ):
            return None

        fs = cls(job_application=job_application)

        fs.asp_id = job_application.to_siae.convention.asp_id
        fs.approval_number = job_application.approval.number

        fs.save()

        # If the jobseeker has no profile, create one
        job_application.job_seeker.get_or_create_job_seeker_profile()

        return fs
