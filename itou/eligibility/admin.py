from django.contrib import admin, messages
from django.contrib.admin.templatetags import admin_list
from django.forms import ValidationError
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html

from itou.approvals import models as approvals_models
from itou.eligibility import models
from itou.eligibility.admin_form import GEIQEligibilityDiagnosisAdminForm, IAEEligibilityDiagnosisAdminForm
from itou.eligibility.models.common import AbstractSelectedAdministrativeCriteria
from itou.job_applications import models as job_applications_models
from itou.utils.admin import (
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    get_admin_view_link,
)


class AbstractSelectedAdministrativeCriteriaInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        for line in self.cleaned_data:
            if line.get("DELETE") and line["id"].certified:
                raise ValidationError("Impossible de supprimer un critère certifié")


class AbstractSelectedAdministrativeCriteriaInline(ItouTabularInline):
    formset = AbstractSelectedAdministrativeCriteriaInlineFormSet
    extra = 0
    raw_id_fields = ("administrative_criteria",)
    fields = (
        "administrative_criteria",
        "certified_display",
        "certified_at",
        "certification_period",
        "data_returned_by_api",
        "created_at",
    )
    readonly_fields = (
        "certified_display",
        "certified_at",
        "certification_period",
        "data_returned_by_api",
        "created_at",
    )

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=AbstractSelectedAdministrativeCriteria._meta.get_field("certified").verbose_name)
    def certified_display(self, obj):
        if not obj.administrative_criteria.is_certifiable:
            return "Non certifiable"
        return admin_list._boolean_icon(obj.certified)


class SelectedAdministrativeCriteriaInline(AbstractSelectedAdministrativeCriteriaInline):
    model = models.EligibilityDiagnosis.administrative_criteria.through


class SelectedGEIQAdministrativeCriteriaInline(AbstractSelectedAdministrativeCriteriaInline):
    model = models.GEIQEligibilityDiagnosis.administrative_criteria.through


class ApprovalInline(ReadonlyMixin, ItouTabularInline):
    model = approvals_models.Approval
    extra = 0
    show_change_link = True
    fields = (
        "start_at",
        "end_at",
        "is_valid",
    )
    readonly_fields = fields

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return obj.is_valid()


class JobApplicationInline(ReadonlyMixin, ItouTabularInline):
    model = job_applications_models.JobApplication
    extra = 0
    show_change_link = True
    fields = (
        "job_seeker",
        "to_company_link",
        "hiring_start_at",
        "hiring_end_at",
        "approval",
    )
    readonly_fields = fields
    list_select_related = ("to_company",)

    @admin.display(description="Entreprise destinataire")
    def to_company_link(self, obj):
        return format_html(
            "{} — SIRET : {} ({})",
            get_admin_view_link(obj.to_company, content=obj.to_company.display_name),
            obj.to_company.siret,
            obj.to_company.kind,
        )


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
    title = "PASS IAE en cours"
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


class AbstractEligibilityDiagnosisAdmin(ItouModelAdmin):
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
        "is_valid",
    )
    search_fields = ("pk", "job_seeker__email", "author__email")
    list_filter = (
        IsValidFilter,
        "author_kind",
    )

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        if obj.pk:
            return obj.is_valid
        return None

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.expires_at = self.model._expiration_date(obj.author)
        # We cannot make this message in the admin form
        if obj.author_prescriber_organization_id and not obj.author_prescriber_organization.is_authorized:
            messages.warning(request, "L'organisation prescriptrice n'est actuellement pas habilitée.")
        super().save_model(request, obj, form, change)


@admin.register(models.EligibilityDiagnosis)
class EligibilityDiagnosisAdmin(AbstractEligibilityDiagnosisAdmin):
    list_display = AbstractEligibilityDiagnosisAdmin.list_display + ("has_approval",)
    list_filter = AbstractEligibilityDiagnosisAdmin.list_filter + (HasApprovalFilter,)
    raw_id_fields = AbstractEligibilityDiagnosisAdmin.raw_id_fields + ("author_siae",)
    readonly_fields = AbstractEligibilityDiagnosisAdmin.readonly_fields + ("is_considered_valid",)
    inlines = (
        SelectedAdministrativeCriteriaInline,
        JobApplicationInline,
        ApprovalInline,
        PkSupportRemarkInline,
    )
    form = IAEEligibilityDiagnosisAdminForm

    @admin.display(boolean=True, description="valide ou PASS IAE en cours")
    def is_considered_valid(self, obj):
        """
        This uses a property of the model and is intended to be used on the
        detail view to avoid too many SQL queries on a list view.
        """
        if obj.pk:
            return obj.is_considered_valid
        return None

    @admin.display(boolean=True, description="PASS IAE en cours")
    def has_approval(self, obj):
        """
        This uses an annotated attribute and is intended to be used on the list view.
        """
        return obj._has_approval

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.resolver_match.view_name.endswith("changelist"):
            qs = qs.has_approval()
        return qs


@admin.register(models.GEIQEligibilityDiagnosis)
class GEIQEligibilityDiagnosisAdmin(AbstractEligibilityDiagnosisAdmin):
    raw_id_fields = AbstractEligibilityDiagnosisAdmin.raw_id_fields + ("author_geiq",)
    readonly_fields = AbstractEligibilityDiagnosisAdmin.readonly_fields + ("allowance_amount",)
    inlines = (
        SelectedGEIQAdministrativeCriteriaInline,
        JobApplicationInline,
        PkSupportRemarkInline,
    )
    form = GEIQEligibilityDiagnosisAdminForm

    @admin.display(description="montant de l'aide")
    def allowance_amount(self, obj):
        return f"{obj.allowance_amount} EUR"


class AbstractAdministrativeCriteriaAdmin(ReadonlyMixin, ItouModelAdmin):
    # Administrative criteria are updated via fixtures
    list_display_links = ("pk", "name")
    list_filter = ("level",)
    readonly_fields = ("created_at",)
    search_fields = ("name", "desc")


@admin.register(models.AdministrativeCriteria)
class AdministrativeCriteriaAdmin(AbstractAdministrativeCriteriaAdmin):
    list_display = (
        "pk",
        "name",
        "level",
        "ui_rank",
        "is_certifiable",
        "created_at",
    )

    @admin.display(boolean=True, description="vérifiable par l'API Particuliers")
    def is_certifiable(self, obj):
        return obj.is_certifiable


@admin.register(models.GEIQAdministrativeCriteria)
class GEIQAdministrativeCriteriaAdmin(AbstractAdministrativeCriteriaAdmin):
    list_display = (
        "pk",
        "name",
        "annex",
        "level",
        "is_certifiable",
        "created_at",
    )
    raw_id_fields = AbstractAdministrativeCriteriaAdmin.raw_id_fields + ("parent",)
    list_filter = AbstractAdministrativeCriteriaAdmin.list_filter + ("annex",)
    ordering = (
        "annex",
        "level",
        "ui_rank",
        "pk",
    )

    @admin.display(boolean=True, description="vérifiable par l'API Particuliers")
    def is_certifiable(self, obj):
        return obj.is_certifiable
