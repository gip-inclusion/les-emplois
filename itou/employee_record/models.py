from django.db import models
from django.utils.translation import gettext_lazy as _

import itou.utils.validators as validators


class Status(models.TextChoices):
    """
    Status of the employee record

    Self-explanatory on the meaning, however:
    - an E.R. can be modified until it is in the PROCESSED state
    - after that, the E.R is "archived" and can't be used for further interaction
    """

    NEW = "NEW", "Nouvelle fiche salarié"
    COMPLETE = "COMPLETE", "Données complètes"
    SENT = "SENT", "Envoyée ASP"
    REJECTED = "REJECTED", "Rejet ASP"
    PROCESSED = "PROCESSED", "Traitée ASP"


class EmployeeRecordQuerySet(models.QuerySet):
    def complete(self):
        return self.filter(status=Status.COMPLETE).order_by("-created_at")

    def sent(self):
        return self.filter(status=Status.SENT).order_by("-created_at")

    def rejected(self):
        return self.filter(status=Status.REJECTED).order_by("-created_at")

    def processed(self):
        return self.filter(status=Status.PROCESSED).order_by("-created_at")

    def archived(self):
        return self.processed().exclude(archived_json=None)


class EmployeeRecord(models.Model):
    """
    EmployeeRecord - Fiche salarié

    Holds information needed for JSON exports and processing by ASP
    """

    created_at = models.DateTimeField(verbose_name=("Date de création"))
    updated_at = models.DateTimeField(verbose_name=("Date de modification"))
    status = models.CharField(max_length=10, verbose_name=_("Statut"), choices=Status.choices, default=Status.NEW)

    # Itou part
    approval = models.ForeignKey(
        "approvals.approval", null=True, on_delete=models.SET_NULL, verbose_name=_("PASS IAE")
    )
    job_application = models.ForeignKey(
        "job_applications.job_application",
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Candidature / embauche"),
    )
    # TODO: This point must be discussed: SIRET might change over time
    siret = models.CharField(max_length=14, verbose_name=_("SIRET"), validators=[validators.validate_siret])

    # ASP processing part
    asp_processing_code = models.CharField(max_length=4, verbose_name=_("Code de traitement ASP"), null=True)
    asp_process_response = models.JSONField(verbose_name=_("Réponse du traitement ASP"), null=True)

    # Once correctly processed by ASP, the Employee Record is archived:
    # - it can't be changed anymore
    # - a serialized version of the employee record is stored (as proof, and for API concerns)
    # The API will not use JSON serializers on a regular basis,
    # except for the archive serialization, which occurs once.
    # It will only return a list of this JSON field for archived employee records.
    archived_json = models.JSONField(verbose_name=_("Fiche salarié au format JSON (archive)"))

    objects = models.Manager.from_queryset(EmployeeRecordQuerySet)()

    class Meta:
        verbose_name = _("Fiche salarié")
        verbose_name_plural = _("Fiches salarié")

    def __str__(self):
        return "["

    # Business methods

    def clean(self):
        # TODO
        pass

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
    def job_seeker_data_complete():
        """
        Jobseeker profile data are complete for further processing
        """
        return True

    @property
    def address_data_complete():
        """
        Jobseeker address is complete for further processing
        """
        return True

    @property
    def siae(self):
        if self.job_application:
            return self.job_application.to_siae

        return None
