from django.contrib import admin
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from itou.eligibility import models


class AdministrativeCriteriaInline(admin.TabularInline):
    model = models.EligibilityDiagnosis.administrative_criteria.through
    extra = 1
    raw_id_fields = ("administrative_criteria",)
    readonly_fields = ("created_at",)


@admin.register(models.EligibilityDiagnosis)
class EligibilityDiagnosisAdmin(admin.ModelAdmin):
    list_display = ("pk", "job_seeker", "author", "author_kind", "created_at", "has_expired")
    list_display_links = ("pk", "job_seeker")
    list_filter = ("author_kind",)
    raw_id_fields = ("job_seeker", "author", "author_siae", "author_prescriber_organization")
    readonly_fields = ("created_at", "updated_at", "expires_at", "has_expired")
    search_fields = ("job_seeker__email", "author__email")
    inlines = (AdministrativeCriteriaInline,)

    def has_expired(self, obj):
        value = _("Non")
        if obj.has_expired:
            value = _("Oui")
        return value

    has_expired.short_description = _("Expiré")

    def expires_at(self, obj):
        return date_format(obj.expires_at)

    expires_at.short_description = _("Date d'expiration")


@admin.register(models.AdministrativeCriteria)
class AdministrativeCriteriaAdmin(admin.ModelAdmin):
    list_display = ("pk", "name", "level", "ui_rank", "created_at")
    list_display_links = ("pk", "name")
    list_filter = ("level",)
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_at",)
    search_fields = ("name", "desc")

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
