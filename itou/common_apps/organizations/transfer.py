from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import TextChoices
from django.utils import timezone
from psycopg.errors import UniqueViolation

from itou.approvals import models as approvals_models
from itou.companies import enums as companies_enums, models as companies_models
from itou.eligibility import models as eligibility_models
from itou.employee_record.models import EmployeeRecord
from itou.geiq_assessments import models as geiq_assessments_models
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.prescribers import models as prescribers_models
from itou.siae_evaluations import models as siae_evaluations_models
from itou.users import models as users_models
from itou.users.utils import merge_job_seeker_assignments


class TransferField(TextChoices):
    IAE_DIAG_CREATED = "iae_diag_created", "Diagnostics IAE créés"
    GEIQ_DIAG_CREATED = "geiq_diag_created", "Diagnostics GEIQ créés"
    EVALUATED_SIAES = "evaluated_siaes", "Contrôles a posteriori IAE"
    GEIQ_ASSESSMENTS = "geiq_assessments", "Bilans d'exécution GEIQ"
    JOB_APPLICATIONS_SENT = "job_applications_sent", "Candidatures envoyées"
    JOB_APPLICATIONS_RECEIVED = "job_applications_received", "Candidatures reçues"
    JOB_APPLICATIONS_TRANSFERRED = "job_applications_transferred", "Candidatures transférées"
    JOB_SEEKER_ASSIGNMENTS = "job_seeker_assignments", "Affectations usagers"
    EMPLOYEE_RECORDS_CREATED = "employee_records_created", "Fiches salarié (transférées via les candidatures reçues)"
    JOB_DESCRIPTIONS = "job_descriptions", "Fiches de poste"
    MEMBERSHIPS = "memberships", "Utilisateurs membres"
    INVITATIONS = "invitations", "Invitations"
    PROLONGATIONS = "prolongations", "Prolongations déclarées"
    PROLONGATION_REQUESTS = "demandes de prolongation", "Demandes de prolongation"
    SUSPENSIONS = "suspensions", "Suspensions déclarées"
    BRAND = "brand", "Enseigne"
    EMAIL = "email", "E-mail"
    NAME = "name", "Nom"
    DESCRIPTION = "description", "Description"
    IS_SEARCHABLE = "is_searchable", "Peut apparaître dans la recherche"
    PHONE = "phone", "Téléphone"
    WEBSITE = "website", "Site web"


COMPANY_TRANSFER_FIELDS = {
    TransferField.IAE_DIAG_CREATED,
    TransferField.GEIQ_DIAG_CREATED,
    TransferField.EVALUATED_SIAES,
    TransferField.GEIQ_ASSESSMENTS,
    TransferField.JOB_APPLICATIONS_SENT,
    TransferField.JOB_APPLICATIONS_RECEIVED,
    TransferField.JOB_APPLICATIONS_TRANSFERRED,
    TransferField.JOB_SEEKER_ASSIGNMENTS,
    TransferField.EMPLOYEE_RECORDS_CREATED,
    TransferField.JOB_DESCRIPTIONS,
    TransferField.MEMBERSHIPS,
    TransferField.INVITATIONS,
    TransferField.PROLONGATIONS,
    TransferField.PROLONGATION_REQUESTS,
    TransferField.SUSPENSIONS,
    TransferField.BRAND,
    TransferField.DESCRIPTION,
    TransferField.IS_SEARCHABLE,
    TransferField.PHONE,
}


PRESCRIBERORG_TRANSFER_FIELDS = {
    TransferField.IAE_DIAG_CREATED,
    TransferField.GEIQ_DIAG_CREATED,
    TransferField.JOB_APPLICATIONS_SENT,
    TransferField.JOB_SEEKER_ASSIGNMENTS,
    TransferField.MEMBERSHIPS,
    TransferField.INVITATIONS,
    TransferField.PROLONGATION_REQUESTS,
    TransferField.DESCRIPTION,
    TransferField.EMAIL,
    TransferField.IS_SEARCHABLE,
    TransferField.NAME,
    TransferField.PHONE,
    TransferField.WEBSITE,
}


class ReportSection(TextChoices):
    JOB_UNLINK = "job_unlink", "Désassociation de fiche de poste"
    ORG_DEACTIVATION = "org_deactivation", "Désactivation structure avec désactivation des membres"


COMPANY_TRANSFER_SPECS = {
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
    TransferField.EVALUATED_SIAES: {
        "related_model": siae_evaluations_models.EvaluatedSiae,
        "related_model_field": "siae",
        "iae_only": True,
    },
    TransferField.GEIQ_ASSESSMENTS: {
        "related_model": geiq_assessments_models.Assessment.companies.through,
        "related_model_field": "company",
        "geiq_only": True,
        "upsert": {
            "key": {"assessment", "company"},
            "fields": {},  # We're not upserting any field: we just need to delete `from_item`
            "merge_function": lambda from_item, _: from_item.delete(),
        },
    },
    TransferField.JOB_APPLICATIONS_SENT: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "sender_company",
    },
    TransferField.JOB_APPLICATIONS_RECEIVED: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "to_company",
    },
    TransferField.JOB_APPLICATIONS_TRANSFERRED: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "transferred_from_id",
    },
    TransferField.JOB_SEEKER_ASSIGNMENTS: {
        "related_model": users_models.JobSeekerAssignment,
        "related_model_field": "company",
        "upsert": {
            "key": {"job_seeker", "professional", "company"},
            "fields": {},  # Don't upsert specific fields but the whole object, as fields depend on each other
            "merge_function": lambda from_item, to_item: merge_job_seeker_assignments(
                assignment_to_delete=from_item, assignment_to_keep=to_item
            ),
        },
    },
    TransferField.EMPLOYEE_RECORDS_CREATED: {
        "related_model": EmployeeRecord,
        "related_model_field": "job_application__to_company",
        "iae_only": True,
        # Nothing modified directly on this model (transfer happens through JOB_APPLICATIONS_RECEIVED)
        "report_only": True,
    },
    TransferField.JOB_DESCRIPTIONS: {
        "related_model": companies_models.JobDescription,
        "related_model_field": "company",
    },
    TransferField.MEMBERSHIPS: {
        "related_model": companies_models.CompanyMembership,
        "related_model_manager": "include_inactive",
        "related_model_field": "company",
        "upsert": {
            "key": {"user", "company"},
            "fields": {
                "is_admin": lambda from_value, to_value: any([from_value, to_value]),
                "is_active": lambda from_value, to_value: any([from_value, to_value]),
            },
        },
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
    TransferField.PROLONGATION_REQUESTS: {
        "related_model": approvals_models.ProlongationRequest,
        "related_model_field": "declared_by_siae",
        "iae_only": True,
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
        "model_field": companies_models.Company._meta.get_field("brand"),
    },
    TransferField.DESCRIPTION: {
        "model_field": companies_models.Company._meta.get_field("description"),
    },
    TransferField.IS_SEARCHABLE: {
        "model_field": companies_models.Company._meta.get_field("is_searchable"),
    },
    TransferField.PHONE: {
        "model_field": companies_models.Company._meta.get_field("phone"),
    },
}

PRESCRIBERORG_TRANSFER_SPECS = {
    TransferField.IAE_DIAG_CREATED: {
        "related_model": eligibility_models.EligibilityDiagnosis,
        "related_model_field": "author_prescriber_organization",
    },
    TransferField.GEIQ_DIAG_CREATED: {
        "related_model": eligibility_models.GEIQEligibilityDiagnosis,
        "related_model_field": "author_prescriber_organization",
    },
    TransferField.JOB_APPLICATIONS_SENT: {
        "related_model": job_applications_models.JobApplication,
        "related_model_field": "sender_prescriber_organization",
    },
    TransferField.JOB_SEEKER_ASSIGNMENTS: {
        "related_model": users_models.JobSeekerAssignment,
        "related_model_field": "prescriber_organization",
        "upsert": {
            "key": {"job_seeker", "professional", "prescriber_organization"},
            "fields": {},  # Don't upsert specific fields but the whole object, as fields depend on each other
            "merge_function": lambda from_item, to_item: merge_job_seeker_assignments(
                assignment_to_delete=from_item, assignment_to_keep=to_item
            ),
        },
    },
    TransferField.MEMBERSHIPS: {
        "related_model": prescribers_models.PrescriberMembership,
        "related_model_manager": "include_inactive",
        "related_model_field": "organization",
        "upsert": {
            "key": {"user", "organization"},
            "fields": {
                "is_admin": lambda from_value, to_value: any([from_value, to_value]),
                "is_active": lambda from_value, to_value: any([from_value, to_value]),
            },
        },
    },
    TransferField.INVITATIONS: {
        "related_model": invitations_models.PrescriberWithOrgInvitation,
        "related_model_field": "organization",
        "to_filter": lambda qs, to_org: qs.exclude(
            email__in=users_models.User.objects.filter(prescribermembership__organization=to_org).values_list(
                "email", flat=True
            )
        ),
    },
    TransferField.PROLONGATION_REQUESTS: {
        "related_model": approvals_models.ProlongationRequest,
        "related_model_field": "prescriber_organization",
    },
    TransferField.DESCRIPTION: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("description"),
    },
    TransferField.EMAIL: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("email"),
    },
    TransferField.IS_SEARCHABLE: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("is_searchable"),
    },
    TransferField.NAME: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("name"),
    },
    TransferField.PHONE: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("phone"),
    },
    TransferField.WEBSITE: {
        "model_field": prescribers_models.PrescriberOrganization._meta.get_field("website"),
    },
}

# Consistency check
assert (COMPANY_TRANSFER_FIELDS | PRESCRIBERORG_TRANSFER_FIELDS) == set(TransferField)
assert set(COMPANY_TRANSFER_SPECS) == COMPANY_TRANSFER_FIELDS
assert set(PRESCRIBERORG_TRANSFER_SPECS) == PRESCRIBERORG_TRANSFER_FIELDS


def get_transfer_queryset(from_company, to_company, spec):
    manager = getattr(spec["related_model"], spec.get("related_model_manager", "objects"))
    queryset = manager.filter(**{spec["related_model_field"]: from_company})
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


def transfer_org_data(
    from_org,
    to_org,
    fields_to_transfer,
    disable_from_org=False,
    allow_asp_to_user_created_transfer=False,
):
    assert type(from_org) is type(to_org)
    is_company_transfer = isinstance(from_org, companies_models.Company)
    TRANSFER_SPECS = COMPANY_TRANSFER_SPECS if is_company_transfer else PRESCRIBERORG_TRANSFER_SPECS

    assert from_org.pk != to_org.pk, (
        f"Cannot transfer from one {'company' if is_company_transfer else 'organization'} to itself"
    )

    if (
        is_company_transfer
        and not allow_asp_to_user_created_transfer
        and from_org.source == companies_enums.CompanySource.ASP
        and to_org.source == companies_enums.CompanySource.USER_CREATED
    ):
        raise TransferError("Impossible de transférer d'une entreprise provenant de l'ASP vers une antenne")

    fields_to_transfer = [TransferField(field_to_transfer) for field_to_transfer in fields_to_transfer]

    reporter = Reporter()
    if (
        is_company_transfer
        and TransferField.JOB_APPLICATIONS_RECEIVED in fields_to_transfer
        and TransferField.JOB_DESCRIPTIONS not in fields_to_transfer
    ):
        for job_application in get_transfer_queryset(
            from_org, to_org, TRANSFER_SPECS[TransferField.JOB_APPLICATIONS_RECEIVED]
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
            from_value = getattr(from_org, model_field.name)
            old_to_value = getattr(to_org, model_field.name)
            if from_value != old_to_value:
                setattr(to_org, model_field.name, from_value)
                save_update_fields.append(model_field.name)
                reporter.add(transfer_field, f"{model_field.name}: {old_to_value!r} remplacé par {from_value!r}")
        else:
            for item in get_transfer_queryset(from_org, to_org, spec):
                if spec.get("iae_only") and not to_org.is_subject_to_iae_rules:
                    raise TransferError(f"Objets impossibles à transférer hors-IAE: {transfer_field.label}")
                elif spec.get("geiq_only") and to_org.kind != companies_enums.CompanyKind.GEIQ:
                    raise TransferError(f"Objets impossibles à transférer hors-GEIQ: {transfer_field.label}")

                if not spec.get("report_only"):
                    setattr(item, spec["related_model_field"], to_org)
                    update_fields = [spec["related_model_field"]]
                    try:
                        item._meta.get_field("updated_at")
                    except FieldDoesNotExist:
                        pass
                    else:
                        update_fields.append("updated_at")

                    try:
                        with transaction.atomic():
                            item.save(update_fields=update_fields)
                    except IntegrityError as e:
                        if not isinstance(e.__cause__, UniqueViolation):
                            raise

                        manager = getattr(spec["related_model"], spec.get("related_model_manager", "objects"))
                        to_item = manager.get(**{field: getattr(item, field) for field in spec["upsert"]["key"]})
                        for field, merge_function in spec["upsert"]["fields"].items():
                            final_value = merge_function(
                                getattr(item, field),
                                getattr(to_item, field),
                            )
                            setattr(to_item, field, final_value)
                        if merge_function := spec["upsert"].get("merge_function"):
                            # The merge function should handle the save() or update()
                            merge_function(item, to_item)
                        else:
                            to_item.save()

                reporter.add(transfer_field, _format_model(item))

    if save_update_fields:
        save_update_fields.append("updated_at")
        to_org.save(update_fields=save_update_fields)

    if disable_from_org:
        if is_company_transfer:
            companies_models.Company.objects.filter(pk=from_org.pk).update(
                block_job_applications=True,
                job_applications_blocked_at=timezone.now(),
                is_searchable=False,
            )
            companies_models.CompanyMembership.objects.filter(company=from_org).update(is_active=False)
        else:
            prescribers_models.PrescriberOrganization.objects.filter(pk=from_org.pk).update(is_searchable=False)
            prescribers_models.PrescriberMembership.objects.filter(organization=from_org).update(is_active=False)
        reporter.add(ReportSection.ORG_DEACTIVATION, _format_model(from_org))
    return reporter
