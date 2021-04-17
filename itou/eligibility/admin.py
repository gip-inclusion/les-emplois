from django.contrib import admin
from django.template.defaultfilters import date as date_filter

from itou.eligibility import models


class AdministrativeCriteriaInline(admin.TabularInline):
    model = models.EligibilityDiagnosis.administrative_criteria.through
    extra = 1
    raw_id_fields = ("administrative_criteria",)
    readonly_fields = ("created_at",)


class IsValidFilter(admin.SimpleListFilter):
    title = "En cours de validité"
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.expired()
        return queryset


class HasApprovalFilter(admin.SimpleListFilter):
    title = "PASS IAE en cours"
    parameter_name = "has_approval"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.has_approval().filter(_has_approval=True)
        if value == "no":
            return queryset.has_approval().filter(_has_approval=False)
        return queryset


@admin.register(models.EligibilityDiagnosis)
class EligibilityDiagnosisAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "job_seeker",
        "author",
        "author_kind",
        "created_at",
        "is_valid",
        "has_approval",
        "expires_at",
    )
    list_display_links = ("pk", "job_seeker")
    list_filter = (IsValidFilter, HasApprovalFilter, "author_kind")
    raw_id_fields = ("job_seeker", "author", "author_siae", "author_prescriber_organization")
    readonly_fields = (
        "created_at",
        "updated_at",
        "expires_at",
        "is_valid",
        "is_considered_valid",
    )
    search_fields = ("job_seeker__email", "author__email")
    inlines = (AdministrativeCriteriaInline,)

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"

    def expires_at(self, obj):
        return date_filter(obj.expires_at, "d F Y H:i")

    expires_at.short_description = "Date d'expiration"

    def is_considered_valid(self, obj):
        """
        This uses a property of the model and is intended to be used on the
        detail view to avoid too many SQL queries on a list view.
        """
        return obj.is_considered_valid

    is_considered_valid.boolean = True
    is_considered_valid.short_description = "Valide ou PASS IAE en cours"

    def has_approval(self, obj):
        """
        This uses an annotated attribute and is intended to be used on the list view.
        """
        return obj._has_approval

    has_approval.boolean = True
    has_approval.short_description = "PASS IAE en cours"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.resolver_match.view_name.endswith("changelist"):
            qs = qs.has_approval()
        return qs


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
