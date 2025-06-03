from django.contrib import admin

from itou.archive import models
from itou.utils.admin import ItouModelAdmin


@admin.register(models.AnonymizedJobSeeker)
class ArchiveJobSeekerAdmin(ItouModelAdmin):
    fields = (
        "date_joined",
        "first_login",
        "last_login",
        "anonymized_at",
        "user_signup_kind",
        "department",
        "title",
        "identity_provider",
        "had_pole_emploi_id",
        "had_nir",
        "lack_of_nir_reason",
        "nir_sex",
        "nir_year",
        "birth_year",
        "count_accepted_applications",
        "count_IAE_applications",
        "count_total_applications",
    )

    readonly_fields = fields


@admin.register(models.AnonymizedApplication)
class ArchiveApplicationAdmin(ItouModelAdmin):
    fields = (
        "job_seeker_birth_year",
        "job_seeker_department_same_as_company_department",
        "sender_kind",
        "sender_company_kind",
        "sender_prescriber_organization_kind",
        "sender_prescriber_organization_authorization_status",
        "company_kind",
        "company_department",
        "company_naf",
        "company_has_convention",
        "anonymized_at",
        "applied_at",
        "processed_at",
        "last_transition_at",
        "had_resume",
        "origin",
        "state",
        "refusal_reason",
        "has_been_transferred",
        "number_of_jobs_applied_for",
        "has_diagoriente_invitation",
        "hiring_rome",
        "hiring_contract_type",
        "hiring_contract_nature",
        "hiring_start_date",
        "hiring_without_approval",
    )

    readonly_fields = fields
