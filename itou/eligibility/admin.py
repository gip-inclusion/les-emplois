from django.contrib import admin

from itou.eligibility import models
from itou.utils.admin import PkSupportRemarkInline


class AbstractAdministrativeCriteriaInline(admin.TabularInline):
    extra = 1
    raw_id_fields = ("administrative_criteria",)
    readonly_fields = ("created_at",)


class AdministrativeCriteriaInline(AbstractAdministrativeCriteriaInline):
    model = models.EligibilityDiagnosis.administrative_criteria.through


class GEIQAdministrativeCriteriaInline(AbstractAdministrativeCriteriaInline):
    model = models.GEIQEligibilityDiagnosis.administrative_criteria.through


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


class AbstractEligibilityDiagnosisAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "job_seeker",
        "author",
        "author_kind",
        "created_at",
        "is_valid",
        "expires_at",
    )
    list_display_links = ("pk", "job_seeker")
    raw_id_fields = (
        "job_seeker",
        "author",
        "author_prescriber_organization",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "expires_at",
    )
    search_fields = ("pk", "job_seeker__email", "author__email")
    list_filter = (
        IsValidFilter,
        "author_kind",
    )

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"


@admin.register(models.EligibilityDiagnosis)
class EligibilityDiagnosisAdmin(AbstractEligibilityDiagnosisAdmin):
    inlines = (
        AdministrativeCriteriaInline,
        PkSupportRemarkInline,
    )

    def get_list_filter(self, request):
        return self.list_filter + (HasApprovalFilter,)

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self.raw_id_fields += ("author_siae",)

    def get_list_display(self, request):
        return self.list_display + ("has_approval",)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (
            "is_valid",
            "is_considered_valid",
        )

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


@admin.register(models.GEIQEligibilityDiagnosis)
class GEIQEligibilityDiagnosisAdmin(AbstractEligibilityDiagnosisAdmin):
    inlines = (
        GEIQAdministrativeCriteriaInline,
        PkSupportRemarkInline,
    )

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)

        self.raw_id_fields += ("author_geiq",)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (
            "has_eligibility",
            "allowance_amount",
        )

    def has_eligibility(self, obj):
        return obj.eligibility_confirmed

    has_eligibility.boolean = True
    has_eligibility.short_description = "Eligibilité GEIQ confirmée"

    def allowance_amount(self, obj):
        return f"{obj.allowance_amount} EUR"

    allowance_amount.short_description = "Montant de l'aide"


class AbstractAdministrativeCriteriaAdmin(admin.ModelAdmin):
    list_display_links = ("pk", "name")
    list_filter = ("level",)
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_at",)
    search_fields = ("name", "desc")

    # Administrative criteria are updated via fixtures

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.AdministrativeCriteria)
class AdministrativeCriteriaAdmin(AbstractAdministrativeCriteriaAdmin):
    list_display = (
        "pk",
        "name",
        "level",
        "ui_rank",
        "created_at",
    )


@admin.register(models.GEIQAdministrativeCriteria)
class GEIQAdministrativeCriteriaAdmin(AbstractAdministrativeCriteriaAdmin):
    list_display = (
        "pk",
        "name",
        "annex",
        "level",
        "created_at",
    )
    ordering = (
        "level",
        "ui_rank",
        "pk",
    )

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)

        self.raw_id_fields += ("parent",)
        self.list_filter += ("annex",)
        self.ordering = ("annex",) + self.ordering
