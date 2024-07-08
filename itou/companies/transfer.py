from django.db.models import TextChoices
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.companies import enums, models
from itou.eligibility import models as eligibility_models
from itou.employee_record.models import EmployeeRecord
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.siae_evaluations.models import EvaluatedSiae
from itou.users import models as users_models


class TransferField(TextChoices):
    IAE_DIAG_CREATED = "iae_diag_created", "Diagnostics IAE créés"
    GEIQ_DIAG_CREATED = "geiq_diag_created", "Diagnostics GEIQ créés"
    JOB_APPLICATIONS_SENT = "job_applications_sent", "Candidatures envoyées"
    JOB_APPLICATIONS_RECEIVED = "job_applications_received", "Candidatures reçues"
    EMPLOYEE_RECORDS_CREATED = "employee_records_created", "Fiches salarié (transférées via les candidatures reçues)"
    JOB_DESCRIPTIONS = "job_descriptions", "Fiches de poste"
    MEMBERSHIPS = "memberships", "Utilisateurs membres"
    INVITATIONS = "invitations", "Invitations"
    PROLONGATIONS = "prolongations", "Prolongations déclarées"
    SUSPENSIONS = "suspensions", "Suspensions déclarées"
    BRAND = "brand", models.Company._meta.get_field("brand").verbose_name.capitalize()
    DESCRIPTION = "description", models.Company._meta.get_field("description").verbose_name.capitalize()
    IS_SEARCHABLE = "is_searchable", models.Company._meta.get_field("is_searchable").verbose_name.capitalize()
    PHONE = "phone", models.Company._meta.get_field("phone").verbose_name.capitalize()


class ReportSection(TextChoices):
    JOB_UNLINK = "job_unlink", "Désassociation de fiche de poste"
    COMPANY_DEACTIVATION = "company_deactivation", "Désactivation entreprise"


TRANSFER_SPECS = {
    TransferField.IAE_DIAG_CREATED: {
        "related_model": eligibility_models.EligibilityDiagnosis,
        "related_model_field": "author_siae",
        "iae_only": True,
    },
    TransferField.GEIQ_DIAG_CREATED: {
        "related_model": eligibility_models.GEIQEligibilityDiagnosis,
        "related_model_field": "author_geiq",
        "geiq_only": True,
    },
    TransferField.JOB_APPLICATIONS_SENT: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "sender_company",
    },
    TransferField.JOB_APPLICATIONS_RECEIVED: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "to_company",
    },
    TransferField.EMPLOYEE_RECORDS_CREATED: {
        "related_model": EmployeeRecord,
        "related_model_field": "job_application__to_company",
        "iae_only": True,
        # Nothing modified directly on this model (transfer happens through JOB_APPLICATIONS_RECEIVED)
        "report_only": True,
    },
    TransferField.JOB_DESCRIPTIONS: {
        "related_model": models.JobDescription,
        "related_model_field": "company",
    },
    TransferField.MEMBERSHIPS: {
        "related_model": models.CompanyMembership,
        "related_model_field": "company",
        "to_filter": lambda qs, to_company: qs.exclude(
            user__in=users_models.User.objects.filter(companymembership__company=to_company)
        ),
    },
    TransferField.INVITATIONS: {
        "related_model": invitations_models.EmployerInvitation,
        "related_model_field": "company",
        "to_filter": lambda qs, to_company: qs.exclude(
            email__in=users_models.User.objects.filter(companymembership__company=to_company).values_list(
                "email", flat=True
            )
        ),
    },
    TransferField.PROLONGATIONS: {
        "related_model": approvals_models.Prolongation,
        "related_model_field": "declared_by_siae",
        "iae_only": True,
    },
    TransferField.SUSPENSIONS: {
        "related_model": approvals_models.Suspension,
        "related_model_field": "siae",
        "iae_only": True,
    },
    TransferField.BRAND: {
        "model_field": models.Company._meta.get_field("brand"),
    },
    TransferField.DESCRIPTION: {
        "model_field": models.Company._meta.get_field("description"),
    },
    TransferField.IS_SEARCHABLE: {
        "model_field": models.Company._meta.get_field("is_searchable"),
    },
    TransferField.PHONE: {
        "model_field": models.Company._meta.get_field("phone"),
    },
}

# Consistency check
assert set(TRANSFER_SPECS) == set(TransferField)


def get_transfer_queryset(from_company, to_company, spec):
    queryset = spec["related_model"].objects.filter(**{spec["related_model_field"]: from_company})
    if (to_filter := spec.get("to_filter")) is not None and to_company:
        queryset = to_filter(queryset, to_company)
    return queryset


class Reporter:
    def __init__(self):
        self.changes = {}

    def add(self, section: TransferField | ReportSection, change: str):
        self.changes.setdefault(section, []).append(change)


class TransferError(Exception):
    pass


def _format_model(obj):
    return f"{obj._meta.label}[{obj.pk}]"


def transfer_company_data(
    from_company,
    to_company,
    fields_to_transfer,
    disable_from_company=False,
    ignore_siae_evaluations=False,
):
    assert from_company.pk != to_company.pk, "Cannot transfer from one company to itself"
    if not ignore_siae_evaluations and EvaluatedSiae.objects.filter(siae=from_company).exists():
        raise TransferError(
            f"Impossible de transférer les objets de l'entreprise ID={from_company.pk}: il y a un contrôle "
            "a posteriori lié. Vérifiez avec l'équipe support."
        )
    if from_company.source == to_company.SOURCE_ASP and to_company.source == to_company.SOURCE_USER_CREATED:
        raise TransferError("Impossible de transférer d'une entreprise provenant de l'ASP vers une antenne")
    fields_to_transfer = [TransferField(field_to_transfer) for field_to_transfer in fields_to_transfer]

    reporter = Reporter()
    if (
        TransferField.JOB_APPLICATIONS_RECEIVED in fields_to_transfer
        and TransferField.JOB_DESCRIPTIONS not in fields_to_transfer
    ):
        for job_application in get_transfer_queryset(
            from_company, to_company, TRANSFER_SPECS[TransferField.JOB_APPLICATIONS_RECEIVED]
        ).prefetch_related("selected_jobs"):
            selected_jobs = sorted(job.pk for job in job_application.selected_jobs.all())
            if selected_jobs:
                reporter.add(
                    ReportSection.JOB_UNLINK,
                    f"{job_application.pk}: {selected_jobs}",
                )
            job_application.selected_jobs.clear()

    save_update_fields = []
    for transfer_field in fields_to_transfer:
        spec = TRANSFER_SPECS[transfer_field]
        if model_field := spec.get("model_field"):
            from_value = getattr(from_company, model_field.name)
            old_to_value = getattr(to_company, model_field.name)
            if from_value != old_to_value:
                setattr(to_company, model_field.name, from_value)
                save_update_fields.append(model_field.name)
                reporter.add(transfer_field, f"{model_field.name}: {old_to_value!r} remplacé par {from_value!r}")
        else:
            for item in get_transfer_queryset(from_company, to_company, spec):
                if spec.get("iae_only") and not to_company.is_subject_to_eligibility_rules:
                    raise TransferError(f"Objets impossibles à transférer hors-IAE: {transfer_field.label}")
                elif spec.get("geiq_only") and to_company.kind != enums.CompanyKind.GEIQ:
                    raise TransferError(f"Objets impossibles à transférer hors-GEIQ: {transfer_field.label}")

                if not spec.get("report_only"):
                    setattr(item, spec["related_model_field"], to_company)
                    item.save(update_fields=[spec["related_model_field"]])
                reporter.add(transfer_field, _format_model(item))

    if save_update_fields:
        to_company.save(update_fields=save_update_fields)

    if disable_from_company:
        models.Company.objects.filter(pk=from_company.pk).update(
            block_job_applications=True,
            job_applications_blocked_at=timezone.now(),
            is_searchable=False,
        )
        reporter.add(ReportSection.COMPANY_DEACTIVATION, _format_model(from_company))
    return reporter
